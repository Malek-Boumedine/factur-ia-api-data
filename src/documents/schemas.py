from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel

from src.documents.models import StatutDocument


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
