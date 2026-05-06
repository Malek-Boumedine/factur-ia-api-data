from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import JSON, TEXT, Column, DateTime, Numeric
from sqlmodel import Field, Relationship, SQLModel

from src.documents.models import Document

if TYPE_CHECKING:
    from src.abonnements.models import Abonnement
    from src.clients.models import Client
    from src.utilisateurs.models import Utilisateur


class TypeFacture(str, Enum):
    FACTURE = "facture"
    AVOIR = "avoir"


class TauxTva(SQLModel, table=True):
    __tablename__ = "taux_tva"

    id: int | None = Field(default=None, primary_key=True)
    taux: Decimal = Field(
        sa_column=Column(Numeric(precision=5, scale=2), unique=True, nullable=False)
    )
    libelle: str = Field(max_length=100)
    code_comptable: str | None = Field(default=None, max_length=50)
    est_actif: bool = Field(default=True)


class StatutFacture(SQLModel, table=True):
    __tablename__ = "statut_facture"

    id: int | None = Field(default=None, primary_key=True)
    libelle: str = Field(unique=True, max_length=50)
    description: str | None = Field(default=None, sa_column=Column(TEXT, nullable=True))


class Facture(SQLModel, table=True):
    __tablename__ = "facture"

    id: int | None = Field(default=None, primary_key=True)
    id_abonnement: int = Field(foreign_key="abonnement.id")
    id_createur: int = Field(foreign_key="utilisateur.id")
    id_client: int | None = Field(default=None, foreign_key="client.id")
    id_document: int | None = Field(default=None, foreign_key="document.id")

    numero_facture: str = Field(unique=True, index=True, max_length=50)
    date_emission: date = Field(default_factory=date.today)
    date_echeance: date | None = Field(default=None)
    devise: str = Field(default="EUR", max_length=3)
    type_facture: TypeFacture = Field(default=TypeFacture.FACTURE)
    id_statut: int = Field(foreign_key="statut_facture.id")

    # snapshots
    siret_emetteur: str | None = Field(default=None, max_length=14)
    siret_destinataire: str | None = Field(default=None, max_length=14)
    snapshot_client: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))

    # totaux
    total_ht: Decimal = Field(max_digits=12, decimal_places=2)
    total_tva: Decimal = Field(max_digits=12, decimal_places=2)
    total_ttc: Decimal = Field(max_digits=12, decimal_places=2)

    mode_paiement: str | None = Field(default=None, max_length=50)
    iban: str | None = Field(default=None, max_length=34)
    reference_commande: str | None = Field(default=None, max_length=100)

    date_creation: datetime = Field(default_factory=lambda: datetime.now(UTC))
    date_modification: datetime | None = Field(
        default=None,
        sa_column=Column(
            DateTime(timezone=True), nullable=True, onupdate=lambda: datetime.now(UTC)
        ),
    )
    notes: str | None = Field(default=None, sa_column=Column(TEXT, nullable=True))

    ## relations
    lignes: list["FactureLigne"] = Relationship(back_populates="facture")
    statut_ref: "StatutFacture" = Relationship()
    createur: "Utilisateur" = Relationship()
    abonnement: "Abonnement" = Relationship()
    client: Optional["Client"] = Relationship()
    document: Optional["Document"] = Relationship()


class FactureLigne(SQLModel, table=True):
    __tablename__ = "facture_ligne"

    id: int | None = Field(default=None, primary_key=True)
    id_facture: int = Field(foreign_key="facture.id")

    ordre: int = Field(default=0)
    designation: str = Field(max_length=255)
    quantite: Decimal = Field(max_digits=10, decimal_places=3)
    unite: str | None = Field(default=None, max_length=50)
    prix_unitaire_ht: Decimal = Field(max_digits=12, decimal_places=2)

    id_taux_tva: int = Field(foreign_key="taux_tva.id")
    montant_ht: Decimal = Field(max_digits=12, decimal_places=2)
    montant_tva: Decimal = Field(max_digits=12, decimal_places=2)
    montant_ttc: Decimal = Field(max_digits=12, decimal_places=2)

    facture: "Facture" = Relationship(back_populates="lignes")
    taux_tva_ref: "TauxTva" = Relationship()


class Avoir(SQLModel, table=True):
    __tablename__ = "avoir"

    id: int | None = Field(default=None, primary_key=True)
    id_facture_origine: int = Field(foreign_key="facture.id")
    id_abonnement: int = Field(foreign_key="abonnement.id")
    id_createur: int = Field(foreign_key="utilisateur.id")

    numero_avoir: str = Field(unique=True, max_length=50)
    date_emission: date = Field(default_factory=date.today)
    motif: str | None = Field(default=None, sa_column=Column(TEXT, nullable=True))

    total_ht: Decimal = Field(max_digits=12, decimal_places=2)
    total_tva: Decimal = Field(max_digits=12, decimal_places=2)
    total_ttc: Decimal = Field(max_digits=12, decimal_places=2)

    date_creation: datetime = Field(default_factory=lambda: datetime.now(UTC))

    facture_origine: "Facture" = Relationship()
    abonnement: "Abonnement" = Relationship()
    createur: "Utilisateur" = Relationship()


class Paiement(SQLModel, table=True):
    __tablename__ = "paiement"

    id: int | None = Field(default=None, primary_key=True)
    id_facture: int = Field(foreign_key="facture.id")
    id_createur: int = Field(foreign_key="utilisateur.id")

    montant: Decimal = Field(max_digits=12, decimal_places=2)
    date_paiement: date = Field(default_factory=date.today)
    mode_paiement: str = Field(max_length=50)
    reference: str | None = Field(
        default=None, max_length=100
    )  # n° chèque, virement ...
    notes: str | None = Field(default=None, sa_column=Column(TEXT, nullable=True))
    date_creation: datetime = Field(default_factory=lambda: datetime.now(UTC))

    facture: "Facture" = Relationship()
    createur: "Utilisateur" = Relationship()
