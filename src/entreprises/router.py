from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel.ext.asyncio.session import AsyncSession

from src.auth.dependencies import get_current_user, verify_tenant_access
from src.core.database import get_session
from src.entreprises.exceptions import (
    ConfigurationManquanteError,
    FormeJuridiqueIntrouvableError,
    SiretDejaUtiliseError,
)
from src.entreprises.models import Entreprise
from src.entreprises.schemas import EntrepriseCreate, EntrepriseRead
from src.entreprises.service import create_entreprise
from src.utilisateurs.models import Utilisateur

router = APIRouter(prefix="/entreprises", tags=["Entreprises"])


@router.get(
    "/me",
    response_model=EntrepriseRead,
    operation_id="get_entreprise_active",
)
async def get_entreprise_active_endpoint(
    entreprise_id: Annotated[int, Depends(verify_tenant_access)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Entreprise:
    """
    Renvoie l'entreprise active (espace de travail courant), résolue via le
    header `x-entreprise-id` après contrôle d'appartenance. Donne au client
    web accès aux informations légales de l'émetteur (SIRET notamment).
    """
    entreprise = await session.get(Entreprise, entreprise_id)
    if entreprise is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Entreprise introuvable.",
        )
    return entreprise


@router.post(
    "/",
    response_model=EntrepriseRead,
    status_code=status.HTTP_201_CREATED,
    operation_id="create_entreprise",
)
async def create_entreprise_endpoint(
    payload: EntrepriseCreate,
    current_user: Annotated[Utilisateur, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Entreprise:
    """
    Crée un premier espace de travail (entreprise) pour l'utilisateur connecté.

    Authentification JWT requise, **sans** header `x-entreprise-id` : l'utilisateur
    n'a pas encore d'entreprise. Il en devient propriétaire (droit admin + rôle
    PROPRIETAIRE) et l'entreprise est souscrite au plan gratuit.
    """
    try:
        return await create_entreprise(session, current_user, payload)
    except SiretDejaUtiliseError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except FormeJuridiqueIntrouvableError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except ConfigurationManquanteError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc
