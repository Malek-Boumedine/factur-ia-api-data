"""
Logique métier de gestion des plans d'abonnement (réservée aux admins
plateforme). Router mince : les règles et la gestion d'erreurs vivent ici.
"""

from datetime import date

from fastapi import HTTPException, status
from sqlalchemy import delete, func
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.abonnements.models import (
    Abonnement,
    EntrepriseAbonnement,
    StatutSouscription,
)
from src.core.db_errors import UniqueConflict, conflict_from_integrity_error
from src.entreprises.models import UtilisateurEntreprise
from src.utilisateurs.models import Utilisateur

# Message unique, réutilisé par la pré-vérification et le filet IntegrityError.
_PLAN_EN_USAGE_DETAIL = (
    "Ce plan est encore souscrit par une ou plusieurs entreprises "
    "et ne peut pas être supprimé."
)

# La FK entreprise_abonnement -> abonnement fait apparaître le nom de la table
# référençante dans le message d'erreur MySQL.
_ABONNEMENT_FK_CONFLICTS = [
    UniqueConflict("entreprise_abonnement", _PLAN_EN_USAGE_DETAIL),
]


async def delete_plan(session: AsyncSession, abonnement_id: int) -> None:
    """
    Supprime un plan d'abonnement.

    Refuse la suppression (409) si le plan est encore référencé par au moins
    une souscription (`entreprise_abonnement`). Défense en profondeur : une
    pré-vérification renvoie un message clair, et la capture de l'IntegrityError
    au commit sert de filet contre une souscription créée entre-temps (race).
    """
    db_plan = await session.get(Abonnement, abonnement_id)
    if db_plan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Plan d'abonnement introuvable",
        )

    # Pré-vérification : plan encore souscrit -> 409 déterministe.
    count = (
        await session.exec(
            select(func.count()).select_from(
                select(EntrepriseAbonnement)
                .where(EntrepriseAbonnement.id_abonnement == abonnement_id)
                .subquery()
            )
        )
    ).one()
    if count > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=_PLAN_EN_USAGE_DETAIL
        )

    # Suppression via une requête Core (et non `session.delete`) : `Abonnement`
    # participe à une relation many-to-many, et l'ORM supprimerait silencieusement
    # les lignes d'association (souscriptions) au lieu de laisser la FK agir. Ici
    # la FK RESTRICT de la base reste le filet en cas de souscription concurrente.
    try:
        await session.execute(
            delete(Abonnement).where(col(Abonnement.id) == abonnement_id)
        )
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise conflict_from_integrity_error(exc, _ABONNEMENT_FK_CONFLICTS) from None


async def _count_active_users(session: AsyncSession, entreprise_id: int) -> int:
    """Nombre d'utilisateurs actifs rattachés à l'entreprise (état vérifiable)."""
    return (
        await session.exec(
            select(func.count()).select_from(
                select(UtilisateurEntreprise)
                .join(
                    Utilisateur,
                    col(Utilisateur.id) == UtilisateurEntreprise.id_utilisateur,
                )
                .where(UtilisateurEntreprise.id_entreprise == entreprise_id)
                .where(col(Utilisateur.est_actif).is_(True))
                .subquery()
            )
        )
    ).one()


async def change_plan(
    session: AsyncSession, entreprise_id: int, id_abonnement: int
) -> EntrepriseAbonnement:
    """
    Change le plan d'abonnement de l'entreprise active (tenant du header).

    Préserve l'historique : la souscription active courante est clôturée
    (``date_fin`` du jour, statut ``expiré``) et une nouvelle souscription est
    créée sur le plan cible — la ligne existante n'est jamais mutée en place.
    L'ensemble est committé en une seule transaction atomique : soit la clôture
    et la création sont toutes deux persistées, soit aucune (pas d'état
    intermédiaire).

    Règles :
    - plan cible inexistant -> 404 ;
    - entreprise déjà sur ce plan -> 409 ;
    - trop d'utilisateurs actifs pour le plan cible -> 409 (bloque uniquement sur
      ``nombre_max_utilisateurs``, un état vérifiable, et non sur le flux de
      factures qui se réinitialise chaque mois).
    """
    plan_cible = await session.get(Abonnement, id_abonnement)
    if plan_cible is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Plan d'abonnement introuvable.",
        )

    # Souscription(s) active(s) courante(s) de l'entreprise (normalement une).
    active_stmt = (
        select(EntrepriseAbonnement)
        .where(EntrepriseAbonnement.id_entreprise == entreprise_id)
        .where(EntrepriseAbonnement.statut == StatutSouscription.ACTIF)
    )
    souscriptions_actives = (await session.exec(active_stmt)).all()

    if any(s.id_abonnement == id_abonnement for s in souscriptions_actives):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="L'entreprise est déjà souscrite à ce plan.",
        )

    # Garde-fou : le plan cible doit pouvoir accueillir les utilisateurs actuels.
    nombre_utilisateurs = await _count_active_users(session, entreprise_id)
    if nombre_utilisateurs > plan_cible.nombre_max_utilisateurs:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Ce plan est limité à {plan_cible.nombre_max_utilisateurs} "
                f"utilisateur(s) et l'entreprise en compte {nombre_utilisateurs} "
                "actif(s). Réduisez le nombre d'utilisateurs avant de passer à "
                "ce plan."
            ),
        )

    aujourd_hui = date.today()

    # Clôture de l'existant (historique préservé) + création de la nouvelle
    # souscription, le tout dans une seule transaction.
    for souscription in souscriptions_actives:
        souscription.date_fin = aujourd_hui
        souscription.statut = StatutSouscription.EXPIRE
        session.add(souscription)

    nouvelle_souscription = EntrepriseAbonnement(
        id_entreprise=entreprise_id,
        id_abonnement=id_abonnement,
        date_debut=aujourd_hui,
        statut=StatutSouscription.ACTIF,
    )
    session.add(nouvelle_souscription)

    await session.commit()
    await session.refresh(nouvelle_souscription)

    return nouvelle_souscription
