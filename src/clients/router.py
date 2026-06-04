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
from src.clients.schemas import (
    ClientCreate,
    ClientRead,
    ClientUpdate,
    SearchSireneSiretResponse,
)
from src.core.database import get_session
from src.integrations.siren_gouv.client import get_company_by_identifier
from src.utilisateurs.models import Utilisateur

router = APIRouter(prefix="/clients", tags=["Ecosystème Client"])
entreprise_id_dep = Annotated[int, Depends(verify_tenant_access)]
current_user_dep = Annotated[Utilisateur, Depends(get_current_user)]
session_dep = Annotated[AsyncSession, Depends(get_session)]


@router.post("/", response_model=ClientRead, status_code=status.HTTP_201_CREATED)
async def create_client(
    client_in: ClientCreate,
    current_user: current_user_dep,
    entreprise_id: entreprise_id_dep,
    _: Annotated[Utilisateur, Depends(RequirePermission("client:create"))],
    session: session_dep,
) -> Any:
    """
    Crée un nouveau client rattaché à l'entreprise (espace de travail) active.
    L'ID du créateur et l'ID de l'entreprise sont renseignés automatiquement.
    """
    # Validation et injection sécurisée des IDs liés au contexte (Tenant + Createur)
    db_client = Client.model_validate(
        client_in,
        update={"id_entreprise": entreprise_id, "id_createur": current_user.id},
    )

    session.add(db_client)
    await session.commit()
    await session.refresh(db_client)

    return db_client


@router.get("/", response_model=list[ClientRead])
async def list_clients(
    entreprise_id: entreprise_id_dep,
    _: Annotated[Utilisateur, Depends(RequirePermission("client:read"))],
    session: session_dep,
) -> Any:
    """
    Récupère la liste de tous les clients appartenant à l'entreprise active.
    """
    statement = select(Client).where(Client.id_entreprise == entreprise_id)
    result = await session.exec(statement)

    return result.all()


@router.get("/{client_id}", response_model=ClientRead)
async def get_client(
    client_id: int,
    entreprise_id: entreprise_id_dep,
    _: Annotated[Utilisateur, Depends(RequirePermission("client:read"))],
    session: session_dep,
) -> Any:
    """
    Récupère les détails d'un client spécifique en s'assurant qu'il
    appartient bien à l'entreprise active (isolation des données).
    """
    statement = select(Client).where(
        Client.id == client_id, Client.id_entreprise == entreprise_id
    )
    result = await session.exec(statement)
    db_client = result.first()

    if not db_client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client introuvable dans cet espace entreprise",
        )

    return db_client


@router.patch("/{client_id}", response_model=ClientRead)
async def update_client(
    client_id: int,
    client_in: ClientUpdate,
    current_user: current_user_dep,
    entreprise_id: entreprise_id_dep,
    _: Annotated[Utilisateur, Depends(RequirePermission("client:update"))],
    session: session_dep,
) -> Any:
    """
    Met à jour partiellement les informations d'un client.
    Met à jour automatiquement l'ID du modificateur pour l'audit.
    """
    statement = select(Client).where(
        Client.id == client_id, Client.id_entreprise == entreprise_id
    )
    result = await session.exec(statement)
    db_client = result.first()

    if not db_client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client introuvable dans cet espace entreprise",
        )

    # Extraction des données envoyées
    client_data = client_in.model_dump(exclude_unset=True)
    for key, value in client_data.items():
        setattr(db_client, key, value)

    # Mise à jour de la traçabilité
    db_client.id_modificateur = current_user.id

    session.add(db_client)
    await session.commit()
    await session.refresh(db_client)

    return db_client


@router.delete("/{client_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_client(
    client_id: int,
    entreprise_id: entreprise_id_dep,
    _: Annotated[Utilisateur, Depends(RequirePermission("client:delete"))],
    session: session_dep,
) -> None:
    """
    Supprime définitivement un client appartenant à l'entreprise active.
    """
    statement = select(Client).where(
        Client.id == client_id, Client.id_entreprise == entreprise_id
    )
    result = await session.exec(statement)
    db_client = result.first()

    if not db_client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client introuvable dans cet espace entreprise",
        )

    await session.delete(db_client)
    await session.commit()


@router.get(
    "/recherche-sirene/{identifiant}",
    response_model=SearchSireneSiretResponse,
    summary="Rechercher une entreprise via son SIREN ou SIRET",
)
async def search_company_by_identifier(identifiant: str) -> dict[str, Any]:
    """
    Interroge l'API gouvernementale pour
    pré-remplir les données d'un client.
    Accepte un SIREN (9 chiffres) ou un SIRET (14 chiffres).
    """
    # on enlève les espaces éventuels
    clean_id = identifiant.replace(" ", "")

    # Validation pour 9 (SIREN) ou 14 (SIRET) chiffres
    if len(clean_id) not in (9, 14) or not clean_id.isdigit():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="L'identifiant doit contenir \
            exactement 9 (SIREN) ou 14 (SIRET) chiffres.",
        )

    company_data = await get_company_by_identifier(clean_id)

    if not company_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Aucune entreprise \
            trouvée pour cet identifiant.",
        )

    return company_data
