from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

from src.documents.models import Document, StatutDocument, StatutExtraction

# Miroir strict du contrat de l'API IA : une valeur hors liste est un signal
# de désynchronisation des contrats (422 souhaité), "inconnu" étant déjà la
# valeur d'échappement côté IA.
TypeDocumentOcr = Literal["devis", "facture", "avoir", "inconnu"]


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

    # Champs additifs du contrat API IA : optionnels (rétrocompatibilité avec
    # une API IA antérieure), null = non calculé. Les clés de `par_champ` ne
    # sont volontairement pas contraintes (robuste si l'IA score un champ de
    # plus) ; les scores en chaînes du contrat sont reparsés en Decimal.
    type_document: TypeDocumentOcr | None = None
    par_champ: dict[str, Decimal] | None = None


class ExtractionOcrRead(BaseModel):
    """Métadonnées OCR exposées au front sur le détail d'une facture.

    Regroupe ce qui vient de l'analyse IA pour le récapitulatif du brouillon :
    score global, type de document détecté et scores par champ (reparsés en
    Decimal depuis les chaînes stockées). Null champ par champ si non calculé.
    """

    score_confiance: Decimal | None = None
    type_document: str | None = None
    par_champ: dict[str, Decimal] | None = None

    model_config = ConfigDict(from_attributes=True)
