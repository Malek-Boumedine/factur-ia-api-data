from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import TEXT, Column
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from src.entreprises.models import Entreprise


class StatutSouscription(str, Enum):
    ACTIF = "actif"
    EXPIRE = "expiré"
    SUSPENDU = "suspendu"
    ANNULE = "annulé"


class EntrepriseAbonnement(SQLModel, table=True):
    """Table de souscription : l'entreprise possède l'abonnement"""

    __tablename__ = "entreprise_abonnement"

    id: int | None = Field(default=None, primary_key=True)
    id_entreprise: int = Field(foreign_key="entreprise.id", index=True)
    id_abonnement: int = Field(foreign_key="abonnement.id")

    date_debut: date = Field(default_factory=date.today)
    date_fin: date | None = Field(default=None)
    statut: StatutSouscription = Field(default=StatutSouscription.ACTIF)
    date_creation: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Abonnement(SQLModel, table=True):
    __tablename__ = "abonnement"

    id: int | None = Field(default=None, primary_key=True)
    libelle: str = Field(unique=True, index=True, max_length=100)
    description: str | None = Field(default=None, sa_column=Column(TEXT, nullable=True))
    tarif: Decimal = Field(default=0, max_digits=10, decimal_places=2)
    nombre_max_utilisateurs: int = Field(default=1)
    nombre_max_factures_mois: int = Field(default=10)

    # Relation Many-to-Many
    entreprises: list["Entreprise"] = Relationship(
        back_populates="abonnements", link_model=EntrepriseAbonnement
    )
