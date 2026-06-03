from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import JSON, Column
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from src.entreprises.models import Entreprise
    from src.utilisateurs.models import Utilisateur


class AuditAction(str, Enum):
    """Énumération des types d'actions tracées dans le journal."""

    CREATION = "CRÉATION"
    MODIFICATION = "MODIFICATION"
    SUPPRESSION = "SUPPRESSION"


class JournalAudit(SQLModel, table=True):
    """
    Trace immuable de toutes les actions (création, modification, suppression)
    effectuées sur les entités de l'application, isolées par entreprise.
    """

    __tablename__ = "journal_audit"

    id: int | None = Field(default=None, primary_key=True)
    id_entreprise: int | None = Field(
        default=None, foreign_key="entreprise.id", index=True
    )
    id_utilisateur: int | None = Field(default=None, foreign_key="utilisateur.id")

    entite: str = Field(max_length=50)
    id_entite: int
    action: AuditAction

    anciennes_valeurs: dict[str, Any] | None = Field(
        default=None, sa_column=Column(JSON)
    )
    nouvelles_valeurs: dict[str, Any] | None = Field(
        default=None, sa_column=Column(JSON)
    )

    adresse_ip: str | None = Field(default=None, max_length=45)
    date_action: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # relations
    utilisateur: Optional["Utilisateur"] = Relationship()
    entreprise: Optional["Entreprise"] = Relationship()
