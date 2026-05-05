from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import Column, Text
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from src.utilisateurs.models import Utilisateur


class CanalNotification(str, Enum):
    DANS_APP = "dans_app"
    COURRIEL = "email"


class TypeNotification(SQLModel, table=True):
    __tablename__ = "type_notification"

    id: int | None = Field(default=None, primary_key=True)
    libelle: str = Field(unique=True, max_length=50)
    description: str | None = Field(default=None, sa_column=Column(Text))
    est_actif: bool = Field(default=True)

    notifications: list["Notification"] = Relationship(back_populates="type_notif")


class Notification(SQLModel, table=True):
    __tablename__ = "notification"

    id: int | None = Field(default=None, primary_key=True)
    id_utilisateur: int = Field(foreign_key="utilisateur.id")
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
    type_notif: "TypeNotification" = Relationship(back_populates="notifications")
