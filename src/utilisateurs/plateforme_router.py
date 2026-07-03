"""
Endpoints de gestion des administrateurs de plateforme.

Router mince : toute la logique et les garde-fous vivent dans `services.py`.
Toutes les routes sont réservées aux administrateurs de plateforme et opèrent
au niveau global (aucun header `x-entreprise-id` requis).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlmodel.ext.asyncio.session import AsyncSession

from src.auth.dependencies import require_admin_plateforme
from src.core.database import get_session
from src.utilisateurs import services
from src.utilisateurs.models import Utilisateur
from src.utilisateurs.schemas import AdminPlateformeRead

router = APIRouter(
    prefix="/admins-plateforme",
    tags=["Administration Plateforme"],
    dependencies=[Depends(require_admin_plateforme)],
)

SessionDep = Annotated[AsyncSession, Depends(get_session)]
AdminDep = Annotated[Utilisateur, Depends(require_admin_plateforme)]


@router.get("/", response_model=list[AdminPlateformeRead])
async def list_admins(session: SessionDep) -> list[Utilisateur]:
    """Liste les administrateurs de la plateforme."""
    return await services.list_platform_admins(session)


@router.get("/recherche-utilisateur", response_model=list[AdminPlateformeRead])
async def search_user(
    session: SessionDep,
    email: Annotated[
        str,
        Query(
            min_length=2,
            description="Fragment d'email à rechercher "
            "(partiel, insensible à la casse).",
        ),
    ],
) -> list[Utilisateur]:
    """
    Recherche des utilisateurs par email pour désigner un candidat à la
    promotion. Réservé aux admins plateforme, sans périmètre d'entreprise.
    """
    return await services.search_users_by_email(session, email)


@router.post("/{utilisateur_id}/promouvoir", response_model=AdminPlateformeRead)
async def promote_admin(
    utilisateur_id: int,
    session: SessionDep,
) -> Utilisateur:
    """
    Promeut un utilisateur au rang d'administrateur de plateforme.
    Ne modifie que le statut plateforme, jamais les rôles métier.
    """
    return await services.promote_platform_admin(session, utilisateur_id)


@router.post("/{utilisateur_id}/revoquer", response_model=AdminPlateformeRead)
async def revoke_admin(
    utilisateur_id: int,
    session: SessionDep,
    current_admin: AdminDep,
) -> Utilisateur:
    """
    Révoque le statut d'administrateur de plateforme d'un utilisateur.
    Le compte reste inchangé par ailleurs (rôles, entreprises, existence).
    """
    return await services.revoke_platform_admin(session, utilisateur_id, current_admin)
