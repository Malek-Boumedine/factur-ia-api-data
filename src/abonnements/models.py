from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from src.utilisateurs.models import Utilisateur


# Enum pour le statut
class SubscriptionStatus(str, Enum):
    ACTIF = "actif"
    EXPIRE = "expiré"
    SUSPENDU = "suspendu"
    ANNULE = "annulé"


class Abonnement(SQLModel, table=True):
    __tablename__ = "abonnement"

    id: int | None = Field(default=None, primary_key=True)
    libelle: str = Field(unique=True, index=True, max_length=100)
    description: str | None = Field(default=None)
    tarif: Decimal = Field(default=0, max_digits=10, decimal_places=2)
    nombre_max_utilisateurs: int = Field(default=1)
    nombre_max_factures_mois: int = Field(default=10)

    # relation Many-to-Many vers Utilisateur (référence par chaîne)
    utilisateurs: list["Utilisateur"] = Relationship(
        back_populates="abonnements", link_model="UtilisateurAbonnement"
    )


class UtilisateurAbonnement(SQLModel, table=True):
    __tablename__ = "utilisateur_abonnement"

    __table_args__ = (
        UniqueConstraint(
            "id_abonnement", "id_utilisateur", name="uq_user_subscription"
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    id_abonnement: int = Field(foreign_key="abonnement.id")
    id_utilisateur: int = Field(foreign_key="utilisateur.id")

    is_admin_abonnement: bool = Field(default=False)
    date_debut: date = Field(default_factory=date.today)
    date_fin: date | None = Field(default=None)

    date_creation: datetime = Field(default_factory=lambda: datetime.now(UTC))

    statut: SubscriptionStatus = Field(default=SubscriptionStatus.ACTIF, max_length=20)
