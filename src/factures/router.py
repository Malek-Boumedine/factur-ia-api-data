from datetime import UTC, date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import selectinload
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.auth.dependencies import get_current_user, verify_tenant_access
from src.clients.models import Client
from src.core.config import settings
from src.core.database import get_session
from src.core.pagination import Page, PaginationParams, apply_search, paginate
from src.documents.models import ExtractionOcr
from src.documents.schemas import ExtractionOcrRead
from src.entreprises.models import Entreprise
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
from src.factures.models import Facture, FactureLigne, StatutFacture, TypeFacture
from src.factures.schemas import (
    FactureCreate,
    FactureListItem,
    FactureReadWithLignes,
    FactureUpdate,
    StatistiquesFactures,
    TransmissionChorusPro,
)
from src.factures.service import (
    create_facture_brouillon,
    delete_facture_brouillon,
    generer_avoir_brouillon,
    update_facture_brouillon,
    valider_facture_brouillon,
)
from src.factures.statistiques import (
    DEVISE_PAR_DEFAUT,
    LIMITE_TOP_CLIENTS_MAX,
    LIMITE_TOP_CLIENTS_PAR_DEFAUT,
    calculer_statistiques,
    resoudre_periode,
)
from src.factures.statuts import est_emise
from src.facturx.conformite import check_facturx_minimum
from src.facturx.exceptions import DonneesFacturXManquantesError
from src.facturx.schemas import RapportConformiteFacturX
from src.facturx.service import facturx_filename, generate_facturx
from src.integrations.chorus_pro.client import ChorusProClient, is_chorus_configured
from src.integrations.chorus_pro.exceptions import ChorusProDepotError, ChorusProError
from src.pdp.models import EvenementPdp
from src.utilisateurs.models import Utilisateur

router = APIRouter(prefix="/factures", tags=["Gestion des Factures"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
CurrentUserDep = Annotated[Utilisateur, Depends(get_current_user)]

# dépendance de sécurité multi-tenant.
TenantDep = Annotated[int, Depends(verify_tenant_access)]


def get_chorus_client() -> ChorusProClient:
    """Fournit le client Chorus Pro (surchargeable dans les tests)."""
    return ChorusProClient()


ChorusClientDep = Annotated[ChorusProClient, Depends(get_chorus_client)]


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


# Déclarée AVANT `/{facture_id}` : FastAPI résout les routes dans l'ordre de
# déclaration, et `/statistiques` serait sinon capturé par le paramètre de
# chemin (422 sur la conversion en entier).
@router.get("/statistiques", response_model=StatistiquesFactures)
async def statistiques_factures(
    session: SessionDep,
    id_entreprise: TenantDep,
    date_min: Annotated[
        date | None,
        Query(
            description="Borne basse (incluse) sur la date d'émission. Par défaut : "
            "premier jour du mois, 11 mois avant `date_max` (12 mois glissants)."
        ),
    ] = None,
    date_max: Annotated[
        date | None,
        Query(
            description="Borne haute (incluse) sur la date d'émission. "
            "Par défaut : aujourd'hui."
        ),
    ] = None,
    devise: Annotated[
        str,
        Query(
            min_length=3,
            max_length=3,
            description="Devise des montants agrégés (ISO 4217). Les documents "
            "libellés dans une autre devise sont exclus des totaux et signalés "
            "dans `devises_exclues` : deux devises ne s'additionnent pas.",
        ),
    ] = DEVISE_PAR_DEFAUT,
    limite_top_clients: Annotated[
        int,
        Query(
            ge=1,
            le=LIMITE_TOP_CLIENTS_MAX,
            description="Nombre de clients renvoyés dans `top_clients`.",
        ),
    ] = LIMITE_TOP_CLIENTS_PAR_DEFAUT,
) -> Any:
    """
    Agrège les statistiques de facturation de l'entreprise active : chiffres
    clés, répartition par statut, évolution mensuelle, top clients et encours.

    Tout est calculé en base (SUM/COUNT/GROUP BY) : la réponse est exacte quel
    que soit le volume, sans pagination ni plafond. Le périmètre couvre les
    seuls documents **émis** (famille non-brouillon) de la période et de la
    devise demandées ; les brouillons sont comptés à part dans `brouillons`.

    Les avoirs sont **soustraits** de tous les montants, quel que soit le signe
    sous lequel ils ont été enregistrés. Une facture annulée reste comptée
    positivement : elle se neutralise avec son avoir.

    Limites assumées, faute de suivi des règlements :
    `restant_a_encaisser` compte une facture partiellement payée pour son
    total (chiffre pessimiste), et `montant_en_retard` en est un
    sous-ensemble — les deux ne s'additionnent pas.
    """
    # Une seule lecture de la date : la période et le calcul du retard doivent
    # se référer au même « aujourd'hui », même à cheval sur minuit.
    aujourd_hui = date.today()
    date_min_effective, date_max_effective = resoudre_periode(
        date_min, date_max, aujourd_hui
    )
    if date_min_effective > date_max_effective:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="date_min doit être antérieure ou égale à date_max.",
        )

    return await calculer_statistiques(
        session=session,
        id_entreprise=id_entreprise,
        date_min=date_min_effective,
        date_max=date_max_effective,
        devise=devise.upper(),
        limite_top_clients=limite_top_clients,
        aujourd_hui=aujourd_hui,
    )


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
    plus récente ; null sinon. `libelle_statut` expose le libellé du statut
    résolu depuis le référentiel (mêmes valeurs que la liste) ; null si le
    référentiel est incohérent.
    """
    statement = (
        select(Facture)
        .where(Facture.id == facture_id, Facture.id_entreprise == id_entreprise)
        .options(
            selectinload(Facture.lignes),  # type: ignore
            selectinload(Facture.statut_ref),  # type: ignore
        )
    )
    result = await session.exec(statement)
    db_facture = result.first()

    if not db_facture:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Facture introuvable dans cet espace entreprise",
        )

    facture_read = FactureReadWithLignes.model_validate(db_facture)
    # Référentiel incohérent (statut orphelin) : null plutôt qu'un 500.
    statut_ref = db_facture.statut_ref
    facture_read.libelle_statut = statut_ref.libelle if statut_ref is not None else None

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


@router.get(
    "/{facture_id}/facturx",
    response_class=Response,
    responses={
        200: {
            "content": {"application/pdf": {}},
            "description": "Fichier Factur-X : PDF/A-3 avec XML CII embarqué "
            "(profil MINIMUM), en téléchargement.",
        }
    },
)
async def download_facturx(
    facture_id: int,
    session: SessionDep,
    id_entreprise: TenantDep,
) -> Response:
    """
    Génère et télécharge le fichier Factur-X (PDF/A-3 + XML CII, profil
    MINIMUM) d'une facture validée. Génération idempotente : rien n'est
    stocké, le fichier est reconstruit à chaque appel depuis les données
    figées à la validation (snapshots SIRET et client).

    Refusé (409) pour un brouillon — le Factur-X n'existe que pour une
    facture émise ; toute facture de la famille validée (validée, payée,
    déposée PDP…) reste téléchargeable. Refusé (409) également si une
    donnée obligatoire du XML manque (ex : SIRET émetteur absent).
    """
    statement = (
        select(Facture)
        .where(Facture.id == facture_id, Facture.id_entreprise == id_entreprise)
        .options(
            selectinload(Facture.lignes).selectinload(  # type: ignore
                FactureLigne.taux_tva_ref  # type: ignore
            ),
            selectinload(Facture.statut_ref),  # type: ignore
        )
    )
    result = await session.exec(statement)
    db_facture = result.first()

    if not db_facture:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Facture introuvable dans cet espace entreprise",
        )

    if not est_emise(db_facture.statut_ref):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Le fichier Factur-X n'est disponible que pour une facture "
            "validée. Validez d'abord ce brouillon.",
        )

    db_entreprise = await session.get(Entreprise, id_entreprise)
    if db_entreprise is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Entreprise émettrice introuvable.",
        )

    try:
        pdf_bytes = generate_facturx(db_facture, db_entreprise)
    except DonneesFacturXManquantesError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{facturx_filename(db_facture)}"'
            )
        },
    )


@router.get(
    "/{facture_id}/facturx/conformite",
    response_model=RapportConformiteFacturX,
)
async def facturx_conformity_report(
    facture_id: int,
    session: SessionDep,
    id_entreprise: TenantDep,
) -> Any:
    """
    Rapport de conformité Factur-X (profil MINIMUM) d'une facture validée,
    sans générer le fichier : présence des données obligatoires, cohérence
    des totaux, validité des SIRET. Les erreurs bloquent la transmission
    (la génération refuserait avec les mêmes règles) ; les avertissements
    sont informatifs. Filet de sécurité avant dépôt sur la PDP.

    La clé de Luhn des SIRET (codes ``seller_siret_luhn_invalid`` /
    ``buyer_siret_luhn_invalid``) est une erreur bloquante par défaut ; si le
    serveur relâche ce contrôle (sandbox Chorus Pro, ``SIRET_LUHN_STRICT=
    False``), ces mêmes codes sont remontés en avertissements.

    Refusé (409) pour un brouillon — comme la génération, le rapport n'a de
    sens que sur des données figées à la validation.
    """
    statement = (
        select(Facture)
        .where(Facture.id == facture_id, Facture.id_entreprise == id_entreprise)
        .options(selectinload(Facture.statut_ref))  # type: ignore
    )
    result = await session.exec(statement)
    db_facture = result.first()

    if not db_facture:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Facture introuvable dans cet espace entreprise",
        )

    if not est_emise(db_facture.statut_ref):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Le rapport de conformité Factur-X n'est disponible que "
            "pour une facture validée. Validez d'abord ce brouillon.",
        )

    db_entreprise = await session.get(Entreprise, id_entreprise)
    if db_entreprise is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Entreprise émettrice introuvable.",
        )

    return check_facturx_minimum(db_facture, db_entreprise)


@router.post(
    "/{facture_id}/transmettre-choruspro",
    response_model=TransmissionChorusPro,
)
async def transmettre_choruspro(
    facture_id: int,
    session: SessionDep,
    id_entreprise: TenantDep,
    chorus_client: ChorusClientDep,
) -> Any:
    """
    Transmet la facture à Chorus Pro (environnement de qualification) :
    vérifie la conformité Factur-X (profil MINIMUM), génère le fichier,
    le dépose en base64 via l'API PISTE (double authentification), puis
    trace le résultat sur la facture (numéro de flux, date, statut
    ``deposee_pdp``) avec un événement PDP.

    Refus : 503 si l'intégration Chorus Pro n'est pas configurée, 409 pour
    un brouillon, une facture non conforme ou déjà transmise avec succès
    (la re-transmission n'est possible qu'après un échec), 502 si le dépôt
    échoue côté Chorus Pro (le libellé explicatif est remonté et la facture
    passe en ``erreur_transmission``).
    """
    if not is_chorus_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="L'intégration Chorus Pro n'est pas configurée sur ce serveur.",
        )

    statement = (
        select(Facture)
        .where(Facture.id == facture_id, Facture.id_entreprise == id_entreprise)
        .options(
            selectinload(Facture.lignes).selectinload(  # type: ignore
                FactureLigne.taux_tva_ref  # type: ignore
            ),
            selectinload(Facture.statut_ref),  # type: ignore
        )
    )
    result = await session.exec(statement)
    db_facture = result.first()

    if not db_facture:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Facture introuvable dans cet espace entreprise",
        )

    if not est_emise(db_facture.statut_ref):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Seule une facture validée peut être transmise à Chorus Pro. "
            "Validez d'abord ce brouillon.",
        )

    # Anti-doublon : le numéro de flux n'est renseigné qu'après un dépôt
    # accepté — la re-transmission reste donc possible après un échec.
    if db_facture.numero_flux_depot_chorus:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Facture déjà transmise à Chorus Pro "
            f"(flux {db_facture.numero_flux_depot_chorus}).",
        )

    db_entreprise = await session.get(Entreprise, id_entreprise)
    if db_entreprise is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Entreprise émettrice introuvable.",
        )

    rapport = check_facturx_minimum(db_facture, db_entreprise)
    if not rapport.conforme:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "Facture non conforme au profil Factur-X MINIMUM : "
                "transmission refusée.",
                "erreurs": [erreur.model_dump() for erreur in rapport.erreurs],
            },
        )

    # Statuts cibles résolus avant tout appel réseau : un référentiel
    # incomplet doit échouer avant le dépôt (jamais de dépôt sans trace).
    result_depose = await session.exec(
        select(StatutFacture).where(StatutFacture.libelle == "deposee_pdp")
    )
    statut_depose = result_depose.first()
    result_erreur = await session.exec(
        select(StatutFacture).where(StatutFacture.libelle == "erreur_transmission")
    )
    statut_erreur = result_erreur.first()
    if (
        statut_depose is None
        or statut_depose.id is None
        or statut_erreur is None
        or statut_erreur.id is None
    ):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Statuts PDP (deposee_pdp / erreur_transmission) non "
            "configurés en base.",
        )
    id_statut_erreur = statut_erreur.id

    try:
        pdf_bytes = generate_facturx(db_facture, db_entreprise)
    except DonneesFacturXManquantesError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e

    source = (
        "CHORUS_PRO_SANDBOX" if "sandbox" in settings.CHORUS_BASE_URL else "CHORUS_PRO"
    )
    statut_avant_id = db_facture.id_statut

    async def record_failure(message: str) -> None:
        """Trace l'échec du dépôt : statut erreur_transmission + événement."""
        db_facture.id_statut = id_statut_erreur
        session.add(
            EvenementPdp(
                id_facture=facture_id,
                id_statut_avant=statut_avant_id,
                id_statut_apres=id_statut_erreur,
                source=source,
                message=message,
            )
        )
        await session.commit()

    try:
        depot = await chorus_client.deposer_flux_facturx(
            pdf_bytes, facturx_filename(db_facture)
        )
    except ChorusProDepotError as exc:
        await record_failure(str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Dépôt refusé par Chorus Pro : {exc.libelle} "
            f"(codeRetour={exc.code_retour}).",
        ) from exc
    except ChorusProError as exc:
        await record_failure(str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc

    db_facture.id_statut = statut_depose.id
    db_facture.numero_flux_depot_chorus = depot.numero_flux_depot
    db_facture.date_transmission_chorus = datetime.now(UTC)
    session.add(
        EvenementPdp(
            id_facture=facture_id,
            id_statut_avant=statut_avant_id,
            id_statut_apres=statut_depose.id,
            source=source,
            message=f"Flux déposé : {depot.numero_flux_depot}",
        )
    )
    await session.commit()

    return TransmissionChorusPro(
        numero_flux_depot=depot.numero_flux_depot,
        date_depot=depot.date_depot,
        syntaxe_flux=depot.syntaxe_flux,
        statut=statut_depose.libelle,
    )


@router.patch("/{facture_id}", response_model=FactureReadWithLignes)
async def update_brouillon_endpoint(
    facture_id: int,
    facture_in: FactureUpdate,
    session: SessionDep,
    id_entreprise: TenantDep,
) -> Any:
    """
    Modifie un brouillon de facture : champs d'en-tête et, si fournies,
    remplacement complet des lignes. Les totaux HT/TVA/TTC sont recalculés
    depuis les lignes à chaque modification.

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
    Génère un avoir (en brouillon) à partir d'une facture émise.

    Toute facture émise (famille non-brouillon : validée, payée, en retard,
    déposée PDP, rejetée PDP…) peut faire l'objet d'un avoir — seul moyen
    légal de corriger une facture inaltérable. Refusé (409) pour un
    brouillon (à valider d'abord), une facture annulée (déjà annulée par
    un avoir) ou un avoir (pas d'avoir d'avoir).
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
