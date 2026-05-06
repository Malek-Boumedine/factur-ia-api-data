from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.auth.dependencies import get_current_user, verify_tenant_access
from src.core.database import get_session
from src.utilisateurs.models import Utilisateur

from .models import Catalogue
from .schemas import CatalogueCreate, CatalogueRead, CatalogueUpdate

router = APIRouter(prefix="/catalogue-produits", tags=["Catalogue Produits"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
CurrentUserDep = Annotated[Utilisateur, Depends(get_current_user)]
TenantDep = Annotated[int, Depends(verify_tenant_access)]


@router.post("/", response_model=CatalogueRead, status_code=status.HTTP_201_CREATED)
async def create_produit(
    produit_in: CatalogueCreate,
    session: SessionDep,
    current_user: CurrentUserDep,
    x_entreprise_id: TenantDep,
) -> Any:
    """
    Ajoute un nouveau produit ou service au catalogue.
    L'ID de l'entreprise et du créateur sont injectés automatiquement.
    """
    db_produit = Catalogue(
        **produit_in.model_dump(),
        id_entreprise=x_entreprise_id,
        id_utilisateur=current_user.id,
    )
    session.add(db_produit)
    await session.commit()
    await session.refresh(db_produit)
    return db_produit


@router.get("/", response_model=list[CatalogueRead])
async def read_produits(
    session: SessionDep,
    x_entreprise_id: TenantDep,
    skip: int = 0,
    limit: int = 100,
) -> Any:
    """
    Récupère tous les produits du catalogue pour l'entreprise en cours.
    """
    statement = (
        select(Catalogue)
        .where(Catalogue.id_entreprise == x_entreprise_id)
        .offset(skip)
        .limit(limit)
    )
    produits = await session.exec(statement)
    return produits.all()


@router.get("/{produit_id}", response_model=CatalogueRead)
async def read_produit(
    produit_id: int,
    session: SessionDep,
    x_entreprise_id: TenantDep,
) -> Any:
    """
    Récupère un produit spécifique par son ID.
    """
    statement = select(Catalogue).where(
        Catalogue.id == produit_id, Catalogue.id_entreprise == x_entreprise_id
    )
    result = await session.exec(statement)
    db_produit = result.first()

    if not db_produit:
        raise HTTPException(status_code=404, detail="Produit non trouvé")
    return db_produit


@router.patch("/{produit_id}", response_model=CatalogueRead)
async def update_produit(
    produit_id: int,
    produit_in: CatalogueUpdate,
    session: SessionDep,
    x_entreprise_id: TenantDep,
) -> Any:
    """
    Met à jour partiellement un produit.
    """
    statement = select(Catalogue).where(
        Catalogue.id == produit_id, Catalogue.id_entreprise == x_entreprise_id
    )
    result = await session.exec(statement)
    db_produit = result.first()

    if not db_produit:
        raise HTTPException(status_code=404, detail="Produit non trouvé")

    update_data = produit_in.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_produit, key, value)

    session.add(db_produit)
    await session.commit()
    await session.refresh(db_produit)
    return db_produit


@router.delete("/{produit_id}")
async def delete_produit(
    produit_id: int,
    session: SessionDep,
    x_entreprise_id: TenantDep,
) -> Any:
    """
    Désactive un produit (Soft Delete).
    """
    statement = select(Catalogue).where(
        Catalogue.id == produit_id, Catalogue.id_entreprise == x_entreprise_id
    )
    result = await session.exec(statement)
    db_produit = result.first()

    if not db_produit:
        raise HTTPException(status_code=404, detail="Produit non trouvé")

    db_produit.est_actif = False
    session.add(db_produit)
    await session.commit()
    return {"message": "Produit désactivé avec succès"}
