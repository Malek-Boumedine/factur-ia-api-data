from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Column, Text
from sqlmodel import Field, Relationship, SQLModel

from src.notifications.models import CanalNotification

if TYPE_CHECKING:
    from src.entreprises.models import Entreprise
    from src.factures.models import Facture
    from src.utilisateurs.models import Utilisateur


class TypeRelance(str, Enum):
    """Définit si la relance a été déclenchée par le système ou par un utilisateur."""

    AUTOMATIQUE = "automatique"
    MANUELLE = "manuelle"


class StatutRelance(str, Enum):
    """Résultat de l'exécution de la relance."""

    ENVOYEE = "envoyée"
    ECHOUEE = "échouée"


class ModeleRelance(SQLModel, table=True):
    """
    Configuration de modèles de messages de relance personnalisés par l'entreprise.
    Définit le délai et le canal pour automatiser les rappels de paiement.
    """

    __tablename__ = "modele_relance"

    id: int | None = Field(default=None, primary_key=True)

    # isolation par entreprise (Tenant)
    id_entreprise: int = Field(foreign_key="entreprise.id", index=True)

    libelle: str = Field(max_length=100)
    delai_jours: int = Field(..., gt=0)  # Nombre de jours après échéance

    type_relance: TypeRelance = Field(default=TypeRelance.AUTOMATIQUE)

    contenu_message: str | None = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    canal: CanalNotification = Field(default=CanalNotification.COURRIEL)

    # relations
    entreprise: "Entreprise" = Relationship()
    relances: list["Relance"] = Relationship(back_populates="modele")


class Relance(SQLModel, table=True):
    """
    Trace historique d'une relance effectuée pour une facture spécifique.
    Contient le message final envoyé et les éventuelles erreurs techniques.
    """

    __tablename__ = "relance"

    id: int | None = Field(default=None, primary_key=True)

    # Clés étrangères
    id_facture: int = Field(foreign_key="facture.id", index=True)
    id_modele_relance: int | None = Field(default=None, foreign_key="modele_relance.id")

    # Facultatif : Utilisateur ayant déclenché la relance (si manuelle)
    id_utilisateur: int | None = Field(default=None, foreign_key="utilisateur.id")

    type_relance: TypeRelance
    date_relance: datetime = Field(default_factory=lambda: datetime.now(UTC))
    statut: StatutRelance = Field(default=StatutRelance.ENVOYEE)

    message_envoye: str | None = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    erreur: str | None = Field(
        default=None, max_length=255
    )  # Motif d'échec (ex: "SMTP Error", "Email non renseigné")

    # relations
    facture: "Facture" = Relationship()
    modele: Optional["ModeleRelance"] = Relationship(back_populates="relances")
    utilisateur: Optional["Utilisateur"] = Relationship()
