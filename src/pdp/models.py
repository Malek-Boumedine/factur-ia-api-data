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
    id_statut_avant: int | None = Field(default=None, foreign_key="statut_facture.id")
    id_statut_apres: int = Field(foreign_key="statut_facture.id")

    source: str | None = Field(default=None, max_length=100)
    message: str | None = Field(default=None, sa_column=Column(Text))
    date_evenement: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # relations
    facture: "Facture" = Relationship()
    statut_avant: "StatutFacture" = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[EvenementPdp.id_statut_avant]"}
    )
    statut_apres: "StatutFacture" = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[EvenementPdp.id_statut_apres]"}
    )


class StatutDeclaration(SQLModel, table=True):
    __tablename__ = "statut_declaration"

    id: int | None = Field(default=None, primary_key=True)
    libelle: str = Field(unique=True, max_length=50)
    description: str | None = Field(default=None, sa_column=Column(Text))

    # relation inverse
    declarations: list["Declaration"] = Relationship(back_populates="statut_ref")


class Declaration(SQLModel, table=True):
    __tablename__ = "declaration"

    id: int | None = Field(default=None, primary_key=True)
    id_abonnement: int = Field(foreign_key="abonnement.id")

    periode_debut: date = Field(...)
    periode_fin: date = Field(...)
    montant_ht: Decimal = Field(max_digits=12, decimal_places=2)
    montant_tva: Decimal = Field(max_digits=12, decimal_places=2)
    montant_ttc: Decimal = Field(
        max_digits=12, decimal_places=2
    )  # contrôle de cohérence TVA

    id_statut_declaration: int = Field(foreign_key="statut_declaration.id")

    reference_envoi: str | None = Field(
        default=None, max_length=100
    )  # accusé de réception PDP/PPF
    date_envoi: datetime | None = Field(default=None)
    date_creation: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # relations
    abonnement: "Abonnement" = Relationship()
    statut_ref: "StatutDeclaration" = Relationship(back_populates="declarations")
