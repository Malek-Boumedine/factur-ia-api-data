"""
Endpoints du référentiel des taux de TVA.

Router mince : la logique vit dans `services.py`. Les taux sont des données
globales, communes à toutes les entreprises : aucune route n'exige le header
`x-entreprise-id`. La lecture est ouverte à tout utilisateur authentifié ;
les écritures sont réservées aux administrateurs de la plateforme.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlmodel.ext.asyncio.session import AsyncSession

from src.auth.dependencies import get_current_user, require_admin_plateforme
from src.core.database import get_session
from src.factures.models import TauxTva
from src.taux_tva import services
from src.taux_tva.schemas import TauxTvaCreate, TauxTvaRead, TauxTvaUpdate
from src.utilisateurs.models import Utilisateur

router = APIRouter(prefix="/taux-tva", tags=["Taux de TVA"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
CurrentUserDep = Annotated[Utilisateur, Depends(get_current_user)]
AdminPlateformeDep = Annotated[Utilisateur, Depends(require_admin_plateforme)]


@router.get("/", response_model=list[TauxTvaRead])
async def list_taux(
    session: SessionDep,
    _: CurrentUserDep,
    est_actif: Annotated[
        bool | None,
        Query(description="Filtre sur le statut actif/inactif (optionnel)."),
    ] = None,
) -> list[TauxTva]:
    """
    Liste les taux de TVA de la plateforme (référentiel global).
    Accessible à tout utilisateur authentifié, sans périmètre d'entreprise.
    """
    return await services.list_taux_tva(session, est_actif)


@router.get("/{taux_tva_id}", response_model=TauxTvaRead)
async def get_taux(
    taux_tva_id: int,
    session: SessionDep,
    _: CurrentUserDep,
) -> TauxTva:
    """Récupère le détail d'un taux de TVA."""
    return await services.get_taux_tva(session, taux_tva_id)


@router.post("/", response_model=TauxTvaRead, status_code=status.HTTP_201_CREATED)
async def create_taux(
    taux_in: TauxTvaCreate,
    session: SessionDep,
    _: AdminPlateformeDep,
) -> TauxTva:
    """
    Crée un nouveau taux de TVA. Réservé aux administrateurs de la
    plateforme. Renvoie une 409 si la valeur du taux existe déjà.
    """
    return await services.create_taux_tva(session, taux_in)


@router.patch("/{taux_tva_id}", response_model=TauxTvaRead)
async def update_taux(
    taux_tva_id: int,
    taux_in: TauxTvaUpdate,
    session: SessionDep,
    _: AdminPlateformeDep,
) -> TauxTva:
    """
    Modifie partiellement un taux de TVA (dont réactivation via
    `est_actif=true`). Réservé aux administrateurs de la plateforme.
    """
    return await services.update_taux_tva(session, taux_tva_id, taux_in)


@router.delete("/{taux_tva_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_taux(
    taux_tva_id: int,
    session: SessionDep,
    _: AdminPlateformeDep,
) -> None:
    """
    Désactive un taux de TVA (soft delete, jamais de suppression physique :
    des factures inaltérables le référencent). Réservé aux administrateurs
    de la plateforme.
    """
    await services.deactivate_taux_tva(session, taux_tva_id)
