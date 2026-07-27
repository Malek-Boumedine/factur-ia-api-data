from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel

from src.documents.models import Document, StatutDocument, StatutExtraction


class DocumentRead(BaseModel):
    """État d'un document uploadé, pour le suivi du traitement par le front.

    `id_facture` pointe vers le brouillon de facture généré par l'OCR :
    renseigné uniquement quand le document est traité, null sinon.
    """

    id: int
    nom_original: str
    statut: StatutDocument
    date_chargement: datetime
    id_facture: int | None = None

    @classmethod
    def from_document(cls, document: Document) -> "DocumentRead":
        """Construit l'élément de liste en résolvant l'id du brouillon lié.

        Même sémantique que la route de suivi : l'id de facture vit sur
        l'extraction réussie la plus récente, uniquement quand le document
        est traité. La relation ``document.extractions`` doit avoir été
        chargée en eager.
        """
        id_facture: int | None = None
        if document.statut == StatutDocument.TRAITE:
            reussies = [
                extraction
                for extraction in document.extractions
                if extraction.statut == StatutExtraction.SUCCES
            ]
            if reussies:
                derniere = max(
                    reussies,
                    key=lambda extraction: (
                        extraction.date_extraction,
                        extraction.id or 0,
                    ),
                )
                id_facture = derniere.id_facture
        item = cls.model_validate(document, from_attributes=True)
        item.id_facture = id_facture
        return item


class LigneOcr(BaseModel):
    designation: str
    quantite: Decimal = Decimal("1.0")
    prix_unitaire_ht: Decimal
    taux_tva: Decimal


class OcrWebhookPayload(BaseModel):
    id_document: int
    score_confiance: Decimal
    siret_emetteur: str | None = None
    siret_destinataire: str | None = None
    numero_facture: str | None = None
    date_emission: date | None = None
    total_ht: Decimal
    total_tva: Decimal
    total_ttc: Decimal
    iban: str | None = None
    lignes: list[LigneOcr] = []
