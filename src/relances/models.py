from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING

from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from src.abonnements.models import Abonnement
    from src.factures.models import Facture
    from src.utilisateurs.models import Utilisateur


class RelanceType(str, Enum):
    AUTOMATIQUE = "automatique"
    MANUELLE = "manuelle"


class RelanceStatus(str, Enum):
    ENVOYEE = "envoyée"
    ECHOUEE = "échouée"


class ModeleRelance(SQLModel, table=True):
    __tablename__ = "modele_relance"

    id: int | None = Field(default=None, primary_key=True)
    id_abonnement: int = Field(foreign_key="abonnement.id")

    libelle: str = Field(max_length=100)
    delai_jours: int
    type: RelanceType
    message_template: str | None = Field(default=None)

    # relations
    abonnement: "Abonnement" = Relationship()
    relances: list["Relance"] = Relationship(back_populates="modele")


class Relance(SQLModel, table=True):
    __tablename__ = "relance"

    id: int | None = Field(default=None, primary_key=True)

    # clés étrangères
    id_facture: int = Field(foreign_key="facture.id")
    id_modele_relance: int | None = Field(default=None, foreign_key="modele_relance.id")
    id_utilisateur: int | None = Field(default=None, foreign_key="utilisateur.id")

    type: RelanceType
    date_relance: datetime = Field(default_factory=lambda: datetime.now(UTC))
    statut: RelanceStatus

    # relations
    facture: "Facture" = Relationship()
    modele: "ModeleRelance" | None = Relationship(back_populates="relances")
    utilisateur: "Utilisateur" | None = Relationship()
