from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import JSON, Column
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from src.entreprises.models import Entreprise
    from src.factures.models import Facture
    from src.utilisateurs.models import Utilisateur


class StatutDocument(str, Enum):
    """Statuts possibles pour un document uploadé."""

    EN_ATTENTE = "en_attente"
    TRAITE = "traité"
    ERREUR = "erreur"


class StatutExtraction(str, Enum):
    """Statuts de retour du traitement OCR/IA."""

    SUCCES = "succès"
    ECHEC = "échec"


class Document(SQLModel, table=True):
    """
    Représente un fichier brut (PDF, Image, ...) uploadé par un utilisateur
    avant son analyse par l'IA.
    """

    __tablename__ = "document"

    id: int | None = Field(default=None, primary_key=True)

    # Isolation par entreprise (Tenant)
    id_entreprise: int = Field(foreign_key="entreprise.id", index=True)
    # Auteur de l'upload
    id_utilisateur: int = Field(foreign_key="utilisateur.id")

    nom_fichier: str = Field(max_length=255)
    date_chargement: datetime = Field(default_factory=lambda: datetime.now(UTC))
    statut: StatutDocument = Field(default=StatutDocument.EN_ATTENTE)

    # relations
    entreprise: "Entreprise" = Relationship()
    utilisateur: "Utilisateur" = Relationship()
    extractions: list["ExtractionOcr"] = Relationship(back_populates="document")


class ExtractionOcr(SQLModel, table=True):
    """
    Résultat structuré de l'extraction de données effectuée par l'IA
    sur un document spécifique.
    """

    __tablename__ = "extraction_ocr"

    id: int | None = Field(default=None, primary_key=True)
    id_document: int = Field(foreign_key="document.id")

    contenu_brut: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    score_confiance: Decimal | None = Field(
        default=None, max_digits=5, decimal_places=2
    )
    date_extraction: datetime = Field(default_factory=lambda: datetime.now(UTC))
    statut: StatutExtraction = Field(default=StatutExtraction.ECHEC)

    # Lien vers la facture finale générée (si succès)
    id_facture: int | None = Field(default=None, foreign_key="facture.id")

    # --- RELATIONS ---
    document: "Document" = Relationship(back_populates="extractions")
    facture: Optional["Facture"] = Relationship()
