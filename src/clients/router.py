from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.auth.dependencies import (
    RequirePermission,
    get_current_user,
    verify_tenant_access,
)
from src.clients.models import Client
from src.clients.schemas import ClientCreate, ClientRead, ClientUpdate
from src.core.database import get_session
from src.utilisateurs.models import Utilisateur

router = APIRouter(prefix="/clients", tags=["Ecosystème Client"])


@router.post("/", response_model=ClientRead, status_code=status.HTTP_201_CREATED)
async def create_client(
    client_in: ClientCreate,
    current_user: Annotated[Utilisateur, Depends(get_current_user)],
    abonnement_id: Annotated[int, Depends(verify_tenant_access)],
    _: Annotated[Utilisateur, Depends(RequirePermission("client:create"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Any:
    # _ est une convention python qui signifie :
    # "J'ai besoin d'exécuter ceci,
    # mais je n'utiliserai pas la valeur retournée dans mon code."
    """
    Crée un nouveau client rattaché à l'abonnement actif.
    L'ID du créateur et l'ID de l'abonnement sont renseignés automatiquement.
    """
    # Validation et injection sécurisée des IDs cachés
    db_client = Client.model_validate(
        client_in,
        update={"id_abonnement": abonnement_id, "id_createur": current_user.id},
    )

    session.add(db_client)
    await session.commit()
    await session.refresh(db_client)

    return db_client


@router.get("/", response_model=list[ClientRead])
async def list_clients(
    abonnement_id: Annotated[int, Depends(verify_tenant_access)],
    _: Annotated[Utilisateur, Depends(RequirePermission("client:read"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Any:
    """
    Récupère la liste de tous les clients appartenant à l'abonnement actif.
    """
    statement = select(Client).where(Client.id_abonnement == abonnement_id)
    result = await session.exec(statement)

    return result.all()


@router.get("/{client_id}", response_model=ClientRead)
async def get_client(
    client_id: int,
    abonnement_id: Annotated[int, Depends(verify_tenant_access)],
    _: Annotated[Utilisateur, Depends(RequirePermission("client:read"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Any:
    """
    Récupère les détails d'un client spécifique en s'assurant qu'il
    appartient bien à l'abonnement actif.
    """
    statement = select(Client).where(
        Client.id == client_id, Client.id_abonnement == abonnement_id
    )
    result = await session.exec(statement)
    db_client = result.first()

    if not db_client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client introuvable dans cet abonnement",
        )

    return db_client


@router.patch("/{client_id}", response_model=ClientRead)
async def update_client(
    client_id: int,
    client_in: ClientUpdate,
    current_user: Annotated[Utilisateur, Depends(get_current_user)],
    abonnement_id: Annotated[int, Depends(verify_tenant_access)],
    _: Annotated[Utilisateur, Depends(RequirePermission("client:update"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Any:
    """
    Met à jour partiellement les informations d'un client.
    Met à jour automatiquement l'ID du modificateur.
    """
    statement = select(Client).where(
        Client.id == client_id, Client.id_abonnement == abonnement_id
    )
    result = await session.exec(statement)
    db_client = result.first()

    if not db_client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client introuvable dans cet abonnement",
        )

    # Extraction des données envoyées (ignore les champs non renseignés)
    client_data = client_in.model_dump(exclude_unset=True)
    for key, value in client_data.items():
        setattr(db_client, key, value)

    # Traçabilité
    db_client.id_modificateur = current_user.id

    session.add(db_client)
    await session.commit()
    await session.refresh(db_client)

    return db_client


@router.delete("/{client_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_client(
    client_id: int,
    abonnement_id: Annotated[int, Depends(verify_tenant_access)],
    _: Annotated[Utilisateur, Depends(RequirePermission("client:delete"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    """
    Supprime un client appartenant à l'abonnement actif.
    """
    statement = select(Client).where(
        Client.id == client_id, Client.id_abonnement == abonnement_id
    )
    result = await session.exec(statement)
    db_client = result.first()

    if not db_client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client introuvable dans cet abonnement",
        )

    await session.delete(db_client)
    await session.commit()
