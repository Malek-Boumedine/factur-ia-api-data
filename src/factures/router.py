from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel.ext.asyncio.session import AsyncSession

from src.auth.dependencies import get_current_user, verify_tenant_access
from src.core.database import get_session
from src.factures.exceptions import StatutNonConfigureError, TauxTvaIntrouvableError
from src.factures.schemas import FactureCreate, FactureReadWithLignes
from src.factures.service import create_facture_brouillon
from src.utilisateurs.models import Utilisateur

router = APIRouter(prefix="/factures", tags=["Gestion des Factures"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
CurrentUserDep = Annotated[Utilisateur, Depends(get_current_user)]

# dépendance de sécurité multi-tenant.
TenantDep = Annotated[int, Depends(verify_tenant_access)]


@router.post(
    "/", response_model=FactureReadWithLignes, status_code=status.HTTP_201_CREATED
)
async def create_brouillon_endpoint(
    facture_in: FactureCreate,
    session: SessionDep,
    current_user: CurrentUserDep,
    id_entreprise: TenantDep,
) -> Any:
    try:
        if current_user.id is None:
            raise HTTPException(status_code=500, detail="ID utilisateur manquant")

        db_facture = await create_facture_brouillon(
            session=session,
            facture_in=facture_in,
            id_entreprise=id_entreprise,
            id_createur=current_user.id,
        )
        return db_facture

    except TauxTvaIntrouvableError as e:
        # Erreur client : Il a envoyé un mauvais ID (HTTP 400 ou 404)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        ) from e

    except StatutNonConfigureError as e:
        # Erreur serveur : La base de données est mal configurée (HTTP 500)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        ) from e
