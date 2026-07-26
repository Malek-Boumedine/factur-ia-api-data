from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import selectinload
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.auth.dependencies import get_current_user, verify_tenant_access
from src.core.database import get_session
from src.factures.exceptions import (
    FacturationError,
    FactureIncompleteError,
    FactureNotFoundError,
    StatutNonConfigureError,
    TauxTvaIntrouvableError,
    TransitionStatutInvalideError,
    TypeFactureNonModifiableError,
)
from src.factures.models import Facture
from src.factures.schemas import FactureCreate, FactureReadWithLignes, FactureUpdate
from src.factures.service import (
    create_facture_brouillon,
    generer_avoir_brouillon,
    update_facture_brouillon,
    valider_facture_brouillon,
)
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


@router.get("/{facture_id}", response_model=FactureReadWithLignes)
async def get_facture(
    facture_id: int,
    session: SessionDep,
    id_entreprise: TenantDep,
) -> Any:
    """
    Récupère le détail d'une facture avec ses lignes, en s'assurant qu'elle
    appartient bien à l'entreprise active (isolation des données).

    Pensée pour l'affichage du récapitulatif d'un brouillon (human-in-the-loop)
    avant validation, mais valable pour toute facture.
    """
    statement = (
        select(Facture)
        .where(Facture.id == facture_id, Facture.id_entreprise == id_entreprise)
        .options(selectinload(Facture.lignes))  # type: ignore
    )
    result = await session.exec(statement)
    db_facture = result.first()

    if not db_facture:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Facture introuvable dans cet espace entreprise",
        )

    return db_facture


@router.patch("/{facture_id}", response_model=FactureReadWithLignes)
async def update_brouillon_endpoint(
    facture_id: int,
    facture_in: FactureUpdate,
    session: SessionDep,
    id_entreprise: TenantDep,
) -> Any:
    """
    Modifie un brouillon de facture : champs d'en-tête et, si fournies,
    remplacement complet des lignes (totaux recalculés).

    Seuls les brouillons sont modifiables : toute tentative sur une facture
    validée est refusée (409, inaltérabilité légale).
    """
    try:
        facture_modifiee = await update_facture_brouillon(
            session=session,
            facture_id=facture_id,
            facture_in=facture_in,
            id_entreprise=id_entreprise,
        )
        return facture_modifiee

    except FactureNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e

    except (TransitionStatutInvalideError, TypeFactureNonModifiableError) as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e

    except TauxTvaIntrouvableError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        ) from e

    except FacturationError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        ) from e


@router.post(
    "/{facture_id}/valider",
    response_model=FactureReadWithLignes,
    status_code=status.HTTP_200_OK,
)
async def valider_brouillon_endpoint(
    facture_id: int,
    session: SessionDep,
    id_entreprise: TenantDep,
) -> Any:
    """
    Valide un brouillon de facture.
    Génère le numéro définitif et fige les données du client (Snapshot).

    Refusé (409) si la facture n'est pas un brouillon ou si le brouillon
    est incomplet (aucun client associé).
    """
    try:
        facture_validee = await valider_facture_brouillon(
            session=session,
            facture_id=facture_id,
            id_entreprise=id_entreprise,
        )
        return facture_validee

    except FactureNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e

    except (TransitionStatutInvalideError, FactureIncompleteError) as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e

    except (StatutNonConfigureError, FacturationError) as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        ) from e


@router.post(
    "/{facture_id}/avoir",
    response_model=FactureReadWithLignes,
    status_code=status.HTTP_201_CREATED,
)
async def generer_avoir_endpoint(
    facture_id: int,
    session: SessionDep,
    current_user: CurrentUserDep,
    id_entreprise: TenantDep,
) -> Any:
    """
    Génère un avoir (en brouillon) à partir d'une facture validée.

    Refusé (409) si la facture source n'est pas au statut 'Validée'.
    """
    try:
        if current_user.id is None:
            raise HTTPException(status_code=500, detail="ID utilisateur manquant")

        db_avoir = await generer_avoir_brouillon(
            session=session,
            facture_id=facture_id,
            id_entreprise=id_entreprise,
            id_createur=current_user.id,
        )
        return db_avoir

    except FactureNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e

    except TransitionStatutInvalideError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e

    except (StatutNonConfigureError, FacturationError) as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        ) from e
