"""
Logique métier de gestion des plans d'abonnement (réservée aux admins
plateforme). Router mince : les règles et la gestion d'erreurs vivent ici.
"""

import calendar
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

# Libellé du plan gratuit seedé, plan de repli à l'expiration.
_FREE_PLAN_LIBELLE = "GRATUITE"

# Message unique, réutilisé par la pré-vérification et le filet IntegrityError.
_PLAN_EN_USAGE_DETAIL = (
    "Ce plan est encore souscrit par une ou plusieurs entreprises "
    "et ne peut pas être supprimé."
)


def add_one_month(d: date) -> date:
    """
    Retourne la date un mois plus tard, bornée au dernier jour du mois cible.

    Robuste aux mois de longueurs différentes (31 janvier + 1 mois -> 28 ou 29
    février), contrairement à un simple « +30 jours ».
    """
    month = d.month + 1
    year = d.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(d.day, last_day))


async def _resoudre_plan_gratuit(session: AsyncSession) -> Abonnement:
    """Retourne le plan gratuit seedé (repli d'expiration) ou lève une 500."""
    result = await session.exec(
        select(Abonnement).where(Abonnement.libelle == _FREE_PLAN_LIBELLE)
    )
    plan = result.first()
    if plan is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                f"Configuration manquante : le plan '{_FREE_PLAN_LIBELLE}' est "
                "introuvable (le seed n'a pas été exécuté)."
            ),
        )
    return plan


async def _get_souscription_active(
    session: AsyncSession, entreprise_id: int
) -> EntrepriseAbonnement | None:
    """
    Souscription active courante de l'entreprise (la plus récente si plusieurs).
    """
    statement = (
        select(EntrepriseAbonnement)
        .where(EntrepriseAbonnement.id_entreprise == entreprise_id)
        .where(EntrepriseAbonnement.statut == StatutSouscription.ACTIF)
        .order_by(
            col(EntrepriseAbonnement.date_debut).desc(),
            col(EntrepriseAbonnement.id).desc(),
        )
    )
    return (await session.exec(statement)).first()


async def reconcile_expired_subscription(
    session: AsyncSession, entreprise_id: int
) -> EntrepriseAbonnement | None:
    """
    Expiration paresseuse (lazy) de la souscription active d'une entreprise.

    Si la souscription active est un plan payant dont l'échéance est passée
    (``date_fin < aujourd'hui``), elle est clôturée (statut ``expiré``) et
    l'entreprise bascule sur le plan gratuit (nouvelle souscription ``ACTIF``,
    ``date_fin`` nulle) — le tout en une seule transaction atomique, pour ne
    jamais laisser l'entreprise sans abonnement actif.

    Le plan gratuit (``date_fin is None``) n'expire jamais : aucun effet. Cas non
    couvert (acceptable MVP) : une entreprise jamais consultée ne verra son
    expiration qu'au prochain accès.

    Retourne la souscription active à jour (éventuellement la nouvelle gratuite),
    ou ``None`` si l'entreprise n'a aucune souscription active.
    """
    active = await _get_souscription_active(session, entreprise_id)
    if active is None:
        return None
    # Plan sans échéance (gratuit) : n'expire jamais.
    if active.date_fin is None:
        return active
    # Échéance non atteinte : encore valide.
    if active.date_fin >= date.today():
        return active

    # Souscription payante échue -> bascule atomique vers le plan gratuit.
    free_plan = await _resoudre_plan_gratuit(session)
    active.statut = StatutSouscription.EXPIRE
    session.add(active)

    nouvelle_souscription = EntrepriseAbonnement(
        id_entreprise=entreprise_id,
        id_abonnement=free_plan.id,
        date_debut=date.today(),
        date_fin=None,
        statut=StatutSouscription.ACTIF,
    )
    session.add(nouvelle_souscription)

    await session.commit()
    await session.refresh(nouvelle_souscription)
    return nouvelle_souscription


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


async def ensure_can_add_active_user(session: AsyncSession, entreprise_id: int) -> None:
    """
    Garde-fou : refuse (409) l'ajout d'un utilisateur actif de plus si
    l'entreprise atteint déjà la limite `nombre_max_utilisateurs` de son plan
    actif. Couvre à la fois la création et la réactivation d'un membre (dans les
    deux cas on ajoute un actif à l'effectif courant).

    Applique d'abord l'expiration paresseuse pour évaluer le plan *réellement*
    actif (un plan payant échu compte comme le plan gratuit). Ne désactive
    jamais de compte et ne bloque jamais l'expiration : un sur-effectif hérité
    d'une expiration reste un état valide, on empêche seulement de l'aggraver.

    Absence de plan actif (état anormal) : on tolère, aucun blocage.
    """
    active = await reconcile_expired_subscription(session, entreprise_id)
    if active is None:
        return
    plan = await session.get(Abonnement, active.id_abonnement)
    if plan is None:
        return

    nombre_utilisateurs = await _count_active_users(session, entreprise_id)
    if nombre_utilisateurs >= plan.nombre_max_utilisateurs:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Votre plan est limité à {plan.nombre_max_utilisateurs} "
                "utilisateur(s). Passez à un plan supérieur pour en ajouter "
                "davantage."
            ),
        )


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

    Échéance : un plan payant (``tarif > 0``) reçoit ``date_fin = date_debut +
    1 mois`` ; le plan gratuit (``tarif == 0``) n'expire jamais (``date_fin`` nulle).

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
    # Le plan gratuit (tarif nul) n'expire jamais ; un plan payant échoit à un
    # mois de sa date de début.
    date_fin = None if plan_cible.tarif == 0 else add_one_month(aujourd_hui)

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
        date_fin=date_fin,
        statut=StatutSouscription.ACTIF,
    )
    session.add(nouvelle_souscription)

    await session.commit()
    await session.refresh(nouvelle_souscription)

    return nouvelle_souscription


async def prolonger_abonnement(
    session: AsyncSession, entreprise_id: int
) -> EntrepriseAbonnement:
    """
    Prolonge d'un mois l'abonnement payant actif de l'entreprise (renouvellement
    manuel, sans paiement pour le MVP) : ``date_fin`` est repoussée d'un mois
    depuis son échéance courante.

    Réconcilie d'abord une éventuelle expiration : un plan déjà échu est retombé
    sur le gratuit, qui n'a pas d'échéance et n'est donc pas prolongeable.

    Règles :
    - aucune souscription active -> 404 ;
    - plan gratuit (rien à prolonger) -> 409.
    """
    active = await reconcile_expired_subscription(session, entreprise_id)
    if active is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Aucune souscription active à prolonger.",
        )
    if active.date_fin is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Le plan gratuit n'expire pas et ne peut pas être prolongé.",
        )

    active.date_fin = add_one_month(active.date_fin)
    session.add(active)
    await session.commit()
    await session.refresh(active)
    return active
