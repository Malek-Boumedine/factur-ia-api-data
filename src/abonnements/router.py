from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.abonnements.models import Abonnement, UtilisateurAbonnement
from src.abonnements.schemas import (
    AbonnementCreate,
    AbonnementRead,
    AbonnementUpdate,
    UtilisateurAbonnementRead,
)
from src.auth.dependencies import RequirePermission, get_current_user
from src.core.database import get_session
from src.utilisateurs.models import Utilisateur

router = APIRouter(prefix="/abonnements", tags=["Gestion des Abonnements"])


@router.get("/", response_model=list[AbonnementRead])
async def list_plans(
    session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[Utilisateur, Depends(get_current_user)],
) -> Any:
    """
    Liste tous les plans d'abonnement disponibles sur la plateforme.
    Accessible par tout utilisateur authentifié.
    """
    statement = select(Abonnement)
    result = await session.exec(statement)
    return result.all()


@router.get("/me", response_model=list[UtilisateurAbonnementRead])
async def get_my_subscriptions(
    current_user: Annotated[Utilisateur, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Any:
    """
    Récupère les abonnements auxquels l'utilisateur actuel est rattaché.
    """
    statement = select(UtilisateurAbonnement).where(
        UtilisateurAbonnement.id_utilisateur == current_user.id
    )
    result = await session.exec(statement)
    return result.all()


@router.post("/", response_model=AbonnementRead, status_code=status.HTTP_201_CREATED)
async def create_plan(
    plan_in: AbonnementCreate,
    _: Annotated[Utilisateur, Depends(RequirePermission("platform:manage"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Any:
    """
    Crée un nouveau plan d'abonnement.
    Réservé aux administrateurs de la plateforme.
    """
    db_plan = Abonnement.model_validate(plan_in)
    session.add(db_plan)
    await session.commit()
    await session.refresh(db_plan)
    return db_plan


@router.patch("/{abonnement_id}", response_model=AbonnementRead)
async def update_plan(
    abonnement_id: int,
    plan_in: AbonnementUpdate,
    _: Annotated[Utilisateur, Depends(RequirePermission("platform:manage"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Any:
    """
    Modifie les caractéristiques d'un plan d'abonnement.
    Réservé aux administrateurs de la plateforme.
    """
    db_plan = await session.get(Abonnement, abonnement_id)
    if not db_plan:
        raise HTTPException(status_code=404, detail="Plan d'abonnement introuvable")

    update_data = plan_in.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_plan, key, value)

    session.add(db_plan)
    await session.commit()
    await session.refresh(db_plan)
    return db_plan


@router.delete("/{abonnement_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_plan(
    abonnement_id: int,
    _: Annotated[Utilisateur, Depends(RequirePermission("platform:manage"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    """
    Supprime un plan d'abonnement.
    Réservé aux administrateurs de la plateforme.
    """
    db_plan = await session.get(Abonnement, abonnement_id)
    if not db_plan:
        raise HTTPException(status_code=404, detail="Plan d'abonnement introuvable")

    await session.delete(db_plan)
    await session.commit()
