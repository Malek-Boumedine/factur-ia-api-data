from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Column, Text
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from src.abonnements.models import Abonnement
    from src.factures.models import Facture, StatutFacture


class EvenementPdp(SQLModel, table=True):
    __tablename__ = "evenement_pdp"

    id: int | None = Field(default=None, primary_key=True)
    id_facture: int = Field(foreign_key="facture.id")
    id_statut_facture: int = Field(foreign_key="statut_facture.id")

    source: str | None = Field(default=None, max_length=100)
    message: str | None = Field(default=None, sa_column=Column(Text))
    date_evenement: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # relations
    facture: "Facture" = Relationship()
    statut_ref: "StatutFacture" = Relationship()


class StatutEReporting(SQLModel, table=True):
    __tablename__ = "statut_e_reporting"

    id: int | None = Field(default=None, primary_key=True)
    libelle: str = Field(unique=True, max_length=50)
    description: str | None = Field(default=None, sa_column=Column(Text))

    # relation inverse
    e_reportings: list["EReporting"] = Relationship(back_populates="statut_ref")


class EReporting(SQLModel, table=True):
    __tablename__ = "e_reporting"

    id: int | None = Field(default=None, primary_key=True)
    id_abonnement: int = Field(foreign_key="abonnement.id")

    periode_debut: date
    periode_fin: date
    montant_ht: Decimal = Field(max_digits=12, decimal_places=2)
    montant_tva: Decimal = Field(max_digits=12, decimal_places=2)

    id_statut_reporting: int = Field(foreign_key="statut_e_reporting.id")

    date_envoi: datetime | None = Field(default=None)
    date_creation: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # relations
    abonnement: "Abonnement" = Relationship()
    statut_ref: "StatutEReporting" = Relationship(back_populates="e_reportings")
