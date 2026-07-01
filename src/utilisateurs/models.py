from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlmodel import Field, Relationship, SQLModel

from src.auth.models import UtilisateurRole
from src.entreprises.models import UtilisateurEntreprise

if TYPE_CHECKING:
    from src.auth.models import Role
    from src.entreprises.models import Entreprise


class Utilisateur(SQLModel, table=True):
    """
    Représente une personne physique sur la plateforme.
    Un utilisateur peut appartenir à plusieurs entreprises (espaces de travail).
    """

    __tablename__ = "utilisateur"

    id: int | None = Field(default=None, primary_key=True)
    nom: str = Field(max_length=255)
    prenom: str = Field(max_length=255)
    adresse: str | None = Field(default=None, max_length=255)
    adresse_complement: str | None = Field(default=None, max_length=255)
    code_postal: str | None = Field(default=None, max_length=10, index=True)
    ville: str | None = Field(default=None, max_length=150, index=True)

    email: str = Field(unique=True, index=True, max_length=255)
    telephone: str | None = Field(default=None, max_length=20)
    hash_mot_de_passe: str = Field(max_length=255)

    date_creation: datetime = Field(default_factory=lambda: datetime.now(UTC))
    date_modification: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column_kwargs={"onupdate": lambda: datetime.now(UTC)},
    )
    date_derniere_connexion: datetime | None = Field(default=None)
    est_actif: bool = Field(default=True)

    # relations
    # rôles globaux sur la plateforme
    roles: list["Role"] = Relationship(
        back_populates="utilisateurs", link_model=UtilisateurRole
    )
    # appartenance aux entreprises
    entreprises: list["Entreprise"] = Relationship(
        back_populates="utilisateurs", link_model=UtilisateurEntreprise
    )
