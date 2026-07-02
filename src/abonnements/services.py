"""
Logique métier de gestion des plans d'abonnement (réservée aux admins
plateforme). Router mince : les règles et la gestion d'erreurs vivent ici.
"""

from fastapi import HTTPException, status
from sqlalchemy import delete, func
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.abonnements.models import Abonnement, EntrepriseAbonnement
from src.core.db_errors import UniqueConflict, conflict_from_integrity_error

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
