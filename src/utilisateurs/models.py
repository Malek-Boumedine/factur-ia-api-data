from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlmodel import Field, Relationship, SQLModel

from src.abonnements.models import UtilisateurAbonnement
from src.auth.models import UtilisateurRole

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
    code_postal: str = Field(max_length=10, index=True)
    ville: str = Field(max_length=150, index=True)

    email: str = Field(unique=True, index=True, max_length=255)
    telephone: str | None = Field(default=None, max_length=20)
    hash_mot_de_passe: str = Field(max_length=255)

    # Dates avec default_factory pour l'insertion et onupdate pour le suivi
    date_creation: datetime = Field(default_factory=lambda: datetime.now(UTC))
    date_modification: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column_kwargs={"onupdate": lambda: datetime.now(UTC)},
    )
    date_derniere_connexion: datetime | None = Field(default=None)
    est_actif: bool = Field(default=True)

    ## Relations
    roles: list["Role"] = Relationship(
        back_populates="utilisateurs", link_model=UtilisateurRole
    )

    abonnements: list["Abonnement"] = Relationship(
        back_populates="utilisateurs", link_model=UtilisateurAbonnement
    )
