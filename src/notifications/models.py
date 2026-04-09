from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import Column, Text
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from src.utilisateurs.models import Utilisateur


class NotificationCanal(str, Enum):
    IN_APP = "in_app"
    EMAIL = "email"


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

    message: str = Field(sa_column=Column(Text))
    canal: NotificationCanal
    est_lu: bool = Field(default=False)
    date_creation: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # relations
    utilisateur: "Utilisateur" = Relationship()
    type_notif: "TypeNotification" = Relationship(back_populates="notifications")
