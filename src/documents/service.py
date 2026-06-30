from datetime import date

from pydantic import ValidationError
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.documents.exceptions import DocumentIntrouvableError
from src.documents.models import (
    Document,
    ExtractionOcr,
    StatutDocument,
    StatutExtraction,
)
from src.documents.schemas import OcrWebhookPayload
from src.factures.exceptions import FacturationError
from src.factures.models import TauxTva
from src.factures.schemas import FactureCreate, FactureLigneCreate
from src.factures.service import create_facture_brouillon


async def _payload_vers_facture_create(
    session: AsyncSession,
    payload: OcrWebhookPayload,
    document: Document,
) -> FactureCreate:
    """
    Traduit le résultat brut de l'IA en un schéma de création de brouillon.

    Résout chaque taux de TVA (ex: 20.00) en son ID de référence, car l'OCR
    renvoie un pourcentage alors que la facture attend un `id_taux_tva`.
    """
    if not payload.lignes:
        raise FacturationError("Aucune ligne exploitable dans le résultat OCR.")

    result_taux = await session.exec(
        select(TauxTva).where(col(TauxTva.est_actif).is_(True))
    )
    taux_map = {t.taux: t.id for t in result_taux.all()}

    lignes: list[FactureLigneCreate] = []
    for ligne in payload.lignes:
        id_taux = taux_map.get(ligne.taux_tva)
        if id_taux is None:
            raise FacturationError(
                f"Taux de TVA {ligne.taux_tva}% absent du référentiel."
            )
        lignes.append(
            FactureLigneCreate(
                designation=ligne.designation,
                quantite=ligne.quantite,
                prix_unitaire_ht=ligne.prix_unitaire_ht,
                id_taux_tva=id_taux,
            )
        )

    return FactureCreate(
        id_document=document.id,
        date_emission=payload.date_emission or date.today(),
        iban=payload.iban,
        reference_commande=payload.numero_facture,
        notes="Brouillon généré automatiquement depuis l'analyse OCR.",
        lignes=lignes,
    )


async def _enregistrer_echec(
    session: AsyncSession, payload: OcrWebhookPayload
) -> ExtractionOcr:
    """Trace un échec de traitement : document en erreur, extraction en échec."""
    document = await session.get(Document, payload.id_document)
    if document is not None:
        document.statut = StatutDocument.ERREUR
        session.add(document)

    extraction = ExtractionOcr(
        id_document=payload.id_document,
        contenu_brut=payload.model_dump(mode="json"),
        score_confiance=payload.score_confiance,
        statut=StatutExtraction.ECHEC,
    )
    session.add(extraction)
    await session.commit()
    await session.refresh(extraction)
    return extraction


async def traiter_callback_ocr(
    session: AsyncSession, payload: OcrWebhookPayload
) -> ExtractionOcr:
    """
    Orchestre le retour OCR : crée automatiquement un brouillon de facture à
    partir des données extraites, puis lie l'extraction à ce brouillon.

    En cas de données inexploitables, le document passe en ERREUR et une
    extraction en ECHEC est tracée (le webhook ne renvoie pas d'erreur 5xx).
    """
    document = await session.get(Document, payload.id_document)
    if document is None:
        raise DocumentIntrouvableError(f"Document {payload.id_document} introuvable.")

    try:
        facture_in = await _payload_vers_facture_create(session, payload, document)
        facture = await create_facture_brouillon(
            session=session,
            facture_in=facture_in,
            id_entreprise=document.id_entreprise,
            id_createur=document.id_utilisateur,
        )
    except (FacturationError, ValidationError):
        await session.rollback()
        return await _enregistrer_echec(session, payload)

    # Succès : on fige le statut et on lie l'extraction au brouillon créé
    document.statut = StatutDocument.TRAITE
    session.add(document)

    extraction = ExtractionOcr(
        id_document=document.id,
        contenu_brut=payload.model_dump(mode="json"),
        score_confiance=payload.score_confiance,
        statut=StatutExtraction.SUCCES,
        id_facture=facture.id,
    )
    session.add(extraction)
    await session.commit()
    await session.refresh(extraction)
    return extraction
