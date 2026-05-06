from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Column, Text
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from src.entreprises.models import Entreprise
    from src.utilisateurs.models import Utilisateur


class CanalNotification(str, Enum):
    """Canaux de diffusion supportés par le système."""

    DANS_APP = "dans_app"
    COURRIEL = "email"


class TypeNotification(SQLModel, table=True):
    """
    Référentiel des types de notifications (ex: Rappel échéance, Facture traitée, etc.).
    Permet de gérer finement les préférences de l'utilisateur par catégorie.
    """

    __tablename__ = "type_notification"

    id: int | None = Field(default=None, primary_key=True)
    libelle: str = Field(unique=True, max_length=50)
    description: str | None = Field(default=None, sa_column=Column(Text))
    est_actif: bool = Field(default=True)

    # relations
    notifications: list["Notification"] = Relationship(back_populates="type_notif")


class Notification(SQLModel, table=True):
    """
    Instance d'une notification adressée à un utilisateur spécifique,
    généralement dans le contexte d'une entreprise (Tenant).
    """

    __tablename__ = "notification"

    id: int | None = Field(default=None, primary_key=True)

    # Destinataire
    id_utilisateur: int = Field(foreign_key="utilisateur.id", index=True)

    # Contexte Entreprise (Tenant)
    id_entreprise: int | None = Field(
        default=None, foreign_key="entreprise.id", index=True
    )

    id_type: int = Field(foreign_key="type_notification.id")

    message: str = Field(sa_column=Column(Text, nullable=False))
    canal: CanalNotification = Field(default=CanalNotification.DANS_APP)
    est_lu: bool = Field(default=False)

    date_creation: datetime = Field(default_factory=lambda: datetime.now(UTC))
    date_lecture: datetime | None = Field(default=None)
    lien_action: str | None = Field(default=None, max_length=255)
    date_expiration: datetime | None = Field(default=None)

    # relations
    utilisateur: "Utilisateur" = Relationship()
    entreprise: Optional["Entreprise"] = Relationship()
    type_notif: "TypeNotification" = Relationship(back_populates="notifications")
