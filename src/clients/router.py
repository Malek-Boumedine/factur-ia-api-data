from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
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
from src.core.db_errors import UniqueConflict, conflict_from_integrity_error
from src.core.pagination import Page, PaginationParams, apply_search, paginate
from src.core.siret import normalize_siret_input
from src.integrations.siren_gouv.client import get_company_by_identifier
from src.utilisateurs.models import Utilisateur

router = APIRouter(prefix="/clients", tags=["Ecosystème Client"])
entreprise_id_dep = Annotated[int, Depends(verify_tenant_access)]
current_user_dep = Annotated[Utilisateur, Depends(get_current_user)]
session_dep = Annotated[AsyncSession, Depends(get_session)]

# Contraintes uniques de la table `client` mappées vers un message clair.
_CLIENT_UNIQUE_CONFLICTS = [
    UniqueConflict("numero_tva", "Un client avec ce numéro de TVA existe déjà."),
    UniqueConflict("siret", "Un client avec ce SIRET existe déjà."),
]


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
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise conflict_from_integrity_error(exc, _CLIENT_UNIQUE_CONFLICTS) from None
    await session.refresh(db_client)

    return db_client


@router.get("/", response_model=Page[ClientRead])
async def list_clients(
    entreprise_id: entreprise_id_dep,
    _: Annotated[Utilisateur, Depends(RequirePermission("client:read"))],
    session: session_dep,
    pagination: Annotated[PaginationParams, Depends()],
    search: Annotated[
        str | None,
        Query(description="Recherche sur raison sociale, SIRET ou email."),
    ] = None,
    est_actif: Annotated[
        bool | None, Query(description="Filtre sur le statut actif/inactif.")
    ] = None,
) -> Any:
    """
    Récupère les clients de l'entreprise active, avec recherche, filtres
    et pagination. La recherche et les filtres s'appliquent toujours à
    l'intérieur du périmètre de l'entreprise (isolation tenant).
    """
    statement = select(Client).where(Client.id_entreprise == entreprise_id)

    if est_actif is not None:
        statement = statement.where(Client.est_actif == est_actif)

    statement = apply_search(
        statement, [Client.raison_sociale, Client.siret, Client.email], search
    )
    statement = statement.order_by(Client.raison_sociale)

    return await paginate(session, statement, pagination)


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

    # Synchronise la date de désactivation avec le statut actif :
    # réactivation -> on efface la date, désactivation -> on l'horodate.
    if "est_actif" in client_data:
        db_client.date_desactivation = (
            None if db_client.est_actif else datetime.now(UTC)
        )

    # Mise à jour de la traçabilité
    db_client.id_modificateur = current_user.id

    session.add(db_client)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise conflict_from_integrity_error(exc, _CLIENT_UNIQUE_CONFLICTS) from None
    await session.refresh(db_client)

    return db_client


@router.delete("/{client_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_client(
    client_id: int,
    current_user: current_user_dep,
    entreprise_id: entreprise_id_dep,
    _: Annotated[Utilisateur, Depends(RequirePermission("client:delete"))],
    session: session_dep,
) -> None:
    """
    Désactive un client (soft delete) de l'entreprise active.

    On ne supprime jamais physiquement un client : des factures peuvent le
    référencer (intégrité + conservation légale). L'opération est idempotente ;
    la réactivation se fait via PATCH avec `est_actif=true`.
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

    if db_client.est_actif:
        db_client.est_actif = False
        db_client.date_desactivation = datetime.now(UTC)
        db_client.id_modificateur = current_user.id
        session.add(db_client)
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
    Accepte un SIREN (9 chiffres) ou un SIRET (14 chiffres), y compris aux
    formats d'affichage courants (espaces — même insécables —, points,
    tirets) : `340 216 121 33798` est normalisé avant l'appel SIRENE.
    """
    clean_id = normalize_siret_input(identifiant)

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
