from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Column, Text
from sqlmodel import Field, Relationship, SQLModel

from src.notifications.models import CanalNotification

if TYPE_CHECKING:
    from src.abonnements.models import Abonnement
    from src.factures.models import Facture
    from src.notifications.models import CanalNotification
    from src.utilisateurs.models import Utilisateur


class TypeRelance(str, Enum):
    AUTOMATIQUE = "automatique"
    MANUELLE = "manuelle"


class StatutRelance(str, Enum):
    ENVOYEE = "envoyée"
    ECHOUEE = "échouée"


class ModeleRelance(SQLModel, table=True):
    __tablename__ = "modele_relance"

    id: int | None = Field(default=None, primary_key=True)
    id_abonnement: int = Field(foreign_key="abonnement.id")

    libelle: str = Field(max_length=100)
    delai_jours: int = Field(
        ..., gt=0
    )  # strictement positif, les ... Ellipsis pour "obligatoire, sans valeur défaut"
    type_relance: TypeRelance
    contenu_message: str | None = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    canal: "CanalNotification" = Field(default="courriel")

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

    type_relance: TypeRelance
    date_relance: datetime = Field(default_factory=lambda: datetime.now(UTC))
    statut: StatutRelance = Field(default=StatutRelance.ENVOYEE)
    message_envoye: str | None = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    erreur: str | None = Field(
        default=None, max_length=255
    )  # motif d'échec si statut=ECHOUEE

    # relations
    facture: "Facture" = Relationship()
    modele: Optional["ModeleRelance"] = Relationship(back_populates="relances")
    utilisateur: Optional["Utilisateur"] = Relationship()
