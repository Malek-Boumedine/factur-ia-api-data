from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from src.abonnements.models import Abonnement
    from src.auth.models import Role


class Utilisateur(SQLModel, table=True):
    __tablename__ = "utilisateur"

    id: int | None = Field(default=None, primary_key=True)
    nom: str = Field(max_length=255)
    prenom: str = Field(max_length=255)
    adresse: str = Field(max_length=255)
    adresse_complement: str | None = Field(default=None, max_length=255)
    # clé étrangère vers la table Ville
    code_postal_id: int = Field(foreign_key="ville.id")

    email: str = Field(unique=True, index=True, max_length=255)
    telephone: str | None = Field(default=None, max_length=20)
    password_hash: str = Field(max_length=255)

    # Dates avec default_factory pour l'insertion et onupdate pour le suivi
    date_creation: datetime = Field(default_factory=lambda: datetime.now(UTC))
    date_modification: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column_kwargs={"onupdate": lambda: datetime.now(UTC)},
    )
    est_actif: bool = Field(default=True)

    ## Relations
    ville: "Ville" = Relationship(back_populates="utilisateurs")
    roles: list["Role"] = Relationship(
        back_populates="utilisateurs", link_model="UtilisateurRole"
    )
    abonnements: list["Abonnement"] = Relationship(
        back_populates="utilisateurs", link_model="UtilisateurAbonnement"
    )


class Ville(SQLModel, table=True):
    __tablename__ = "ville"

    id: int | None = Field(default=None, primary_key=True)
    code_postal: str = Field(max_length=10, index=True)
    commune: str = Field(max_length=150)

    # relation inverse pour voir les habitants d'une ville
    utilisateurs: list["Utilisateur"] = Relationship(back_populates="ville")
