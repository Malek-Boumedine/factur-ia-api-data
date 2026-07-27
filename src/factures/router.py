from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import selectinload
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.auth.dependencies import get_current_user, verify_tenant_access
from src.clients.models import Client
from src.core.database import get_session
from src.core.pagination import Page, PaginationParams, apply_search, paginate
from src.documents.models import ExtractionOcr
from src.documents.schemas import ExtractionOcrRead
from src.factures.exceptions import (
    FacturationError,
    FactureIncompleteError,
    FactureNotFoundError,
    NumerotationConcurrenceError,
    StatutNonConfigureError,
    TauxTvaIntrouvableError,
    TransitionStatutInvalideError,
    TypeFactureNonModifiableError,
)
from src.factures.models import Facture, StatutFacture, TypeFacture
from src.factures.schemas import (
    FactureCreate,
    FactureListItem,
    FactureReadWithLignes,
    FactureUpdate,
)
from src.factures.service import (
    create_facture_brouillon,
    delete_facture_brouillon,
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


@router.get("/", response_model=Page[FactureListItem])
async def list_factures(
    session: SessionDep,
    id_entreprise: TenantDep,
    pagination: Annotated[PaginationParams, Depends()],
    search: Annotated[
        str | None,
        Query(
            description="Recherche sur numéro de facture, référence de commande "
            "ou raison sociale du client."
        ),
    ] = None,
    statut: Annotated[
        str | None,
        Query(
            description="Filtre sur le libellé du statut (insensible à la casse). "
            "Cas particulier : 'Validée' (ou 'validee'/'validees') sélectionne "
            "toute la famille non-brouillon (validée, payee, en_retard, statuts "
            "PDP…) pour l'onglet « Validées ». Toute autre valeur filtre sur le "
            "libellé exact (ex: Brouillon, payee, en_retard)."
        ),
    ] = None,
    type_facture: Annotated[
        TypeFacture | None,
        Query(description="Filtre sur le type de document (facture ou avoir)."),
    ] = None,
    id_client: Annotated[
        int | None,
        Query(description="Filtre sur le client destinataire."),
    ] = None,
    date_emission_min: Annotated[
        date | None,
        Query(description="Borne basse (incluse) sur la date d'émission."),
    ] = None,
    date_emission_max: Annotated[
        date | None,
        Query(description="Borne haute (incluse) sur la date d'émission."),
    ] = None,
) -> Any:
    """
    Récupère les factures de l'entreprise active, avec recherche, filtres et
    pagination — les plus récentes d'abord. La recherche et les filtres
    s'appliquent toujours à l'intérieur du périmètre de l'entreprise
    (isolation tenant).

    Chaque élément expose ``nom_destinataire`` (snapshot figé pour une
    facture validée, raison sociale du client lié pour un brouillon) et
    ``libelle_statut`` (libellé du référentiel, pour le badge de statut).
    """
    # Left join client : recherche sur la raison sociale sans exclure les
    # factures sans client. Eager load pour résoudre nom_destinataire et
    # libelle_statut sans N+1.
    statement = (
        select(Facture)
        .where(Facture.id_entreprise == id_entreprise)
        .join(Client, onclause=col(Facture.id_client) == col(Client.id), isouter=True)
        .options(
            selectinload(Facture.client),  # type: ignore
            selectinload(Facture.statut_ref),  # type: ignore
        )
    )

    if statut is not None:
        statement = statement.join(
            StatutFacture, onclause=col(Facture.id_statut) == col(StatutFacture.id)
        )
        if statut.lower() in {"validée", "validee", "validees"}:
            # Onglet « Validées » : toute la famille non-brouillon, car une
            # facture validée qui progresse (payee, en_retard, statuts PDP…)
            # doit rester visible dans cet onglet.
            statement = statement.where(~col(StatutFacture.libelle).ilike("brouillon"))
        else:
            # ilike sans joker : égalité insensible à la casse sur le libellé
            statement = statement.where(col(StatutFacture.libelle).ilike(statut))
    if type_facture is not None:
        statement = statement.where(Facture.type_facture == type_facture)
    if id_client is not None:
        statement = statement.where(Facture.id_client == id_client)
    if date_emission_min is not None:
        statement = statement.where(Facture.date_emission >= date_emission_min)
    if date_emission_max is not None:
        statement = statement.where(Facture.date_emission <= date_emission_max)

    statement = apply_search(
        statement,
        [
            col(Facture.numero_facture),
            col(Facture.reference_commande),
            col(Client.raison_sociale),
        ],
        search,
    )
    statement = statement.order_by(
        col(Facture.date_emission).desc(), col(Facture.id).desc()
    )

    page = await paginate(session, statement, pagination)
    page.items = [FactureListItem.from_facture(facture) for facture in page.items]
    return page


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
    avant validation, mais valable pour toute facture. Si la facture est issue
    d'un OCR, `extraction` expose les métadonnées d'analyse (score global,
    type de document détecté, scores par champ) depuis l'extraction liée la
    plus récente ; null sinon.
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

    facture_read = FactureReadWithLignes.model_validate(db_facture)

    result_extraction = await session.exec(
        select(ExtractionOcr)
        .where(col(ExtractionOcr.id_facture) == facture_id)
        .order_by(
            col(ExtractionOcr.date_extraction).desc(), col(ExtractionOcr.id).desc()
        )
        .limit(1)
    )
    extraction = result_extraction.first()
    if extraction is not None:
        facture_read.extraction = ExtractionOcrRead.model_validate(extraction)

    return facture_read


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


@router.delete("/{facture_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_brouillon_endpoint(
    facture_id: int,
    session: SessionDep,
    id_entreprise: TenantDep,
) -> None:
    """
    Supprime un brouillon de facture et ses lignes.

    Refusé (409) si la facture n'est pas un brouillon : une facture validée
    est immuable et ne peut jamais être supprimée (inaltérabilité légale).
    Le document source et son extraction OCR sont conservés (trace).
    """
    try:
        await delete_facture_brouillon(
            session=session,
            facture_id=facture_id,
            id_entreprise=id_entreprise,
        )

    except FactureNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e

    except TransitionStatutInvalideError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e

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

    Refusé (409) si la facture n'est pas un brouillon, si le brouillon est
    incomplet (aucun client associé), ou en cas de conflit de numérotation
    persistant lors de validations simultanées (réessayer la requête).
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

    except (
        TransitionStatutInvalideError,
        FactureIncompleteError,
        NumerotationConcurrenceError,
    ) as e:
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
