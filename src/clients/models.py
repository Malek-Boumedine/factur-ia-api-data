from datetime import UTC, datetime
from typing import TYPE_CHECKING, Optional

from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from src.abonnements.models import Abonnement
    from src.utilisateurs.models import Utilisateur, Ville


class Client(SQLModel, table=True):
    __tablename__ = "client"

    id: int | None = Field(default=None, primary_key=True)

    id_abonnement: int = Field(foreign_key="abonnement.id")
    id_createur: int = Field(foreign_key="utilisateur.id")

    raison_sociale: str = Field(unique=True, index=True, max_length=255)
    siret: str | None = Field(default=None, unique=True, index=True, max_length=14)

    numero_tva: str | None = Field(default=None, unique=True, max_length=20)

    adresse: str | None = Field(default=None, max_length=255)
    adresse_complement: str | None = Field(default=None, max_length=255)
    code_postal_id: int | None = Field(default=None, foreign_key="ville.id")

    email: str | None = Field(default=None, unique=True, index=True, max_length=255)

    telephone: str | None = Field(default=None, max_length=20)
    est_actif: bool = Field(default=True)

    date_creation: datetime = Field(default_factory=lambda: datetime.now(UTC))

    date_modification: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column_kwargs={"onupdate": lambda: datetime.now(UTC)},
    )

    # Relations
    ville: Optional["Ville"] = Relationship()
    createur: "Utilisateur" = Relationship()
    abonnement: "Abonnement" = Relationship()
