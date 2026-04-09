from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, Column
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from src.abonnements.models import Abonnement
    from src.factures.models import Facture
    from src.utilisateurs.models import Utilisateur


class DocumentStatus(str, Enum):
    EN_ATTENTE = "en_attente"
    TRAITE = "traité"
    ERREUR = "erreur"


class ExtractionStatus(str, Enum):
    SUCCES = "succès"
    ECHEC = "échec"


class Document(SQLModel, table=True):
    __tablename__ = "document"

    id: int | None = Field(default=None, primary_key=True)
    id_abonnement: int = Field(foreign_key="abonnement.id")
    id_utilisateur: int = Field(foreign_key="utilisateur.id")

    nom_fichier: str = Field(max_length=255)
    date_chargement: datetime = Field(default_factory=lambda: datetime.now(UTC))
    statut: DocumentStatus = Field(default=DocumentStatus.EN_ATTENTE)

    # relations
    abonnement: "Abonnement" = Relationship()
    utilisateur: "Utilisateur" = Relationship()
    extractions: list["ExtractionOcr"] = Relationship(back_populates="document")


class ExtractionOcr(SQLModel, table=True):
    __tablename__ = "extraction_ocr"

    id: int | None = Field(default=None, primary_key=True)
    id_document: int = Field(foreign_key="document.id")

    contenu_brut: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    score_confiance: Decimal | None = Field(
        default=None, max_digits=5, decimal_places=2
    )
    date_extraction: datetime = Field(default_factory=lambda: datetime.now(UTC))
    statut: ExtractionStatus

    id_facture: int | None = Field(default=None, foreign_key="facture.id")

    # relations
    document: "Document" = Relationship(back_populates="extractions")
    facture: "Facture" | None = Relationship()
