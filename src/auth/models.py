from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import TEXT, Column
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from src.utilisateurs.models import Utilisateur


class PermissionRole(SQLModel, table=True):
    """Table pivot : Associe un rôle à une ou plusieurs permissions."""

    __tablename__ = "permission_role"

    id_role: int = Field(foreign_key="role.id", primary_key=True)
    id_permission: int = Field(foreign_key="permission.id", primary_key=True)


class UtilisateurRole(SQLModel, table=True):
    """
    Table pivot : Associe un utilisateur à un rôle.
    - Si id_entreprise est NULL : C'est un rôle global
    - Si id_entreprise est rempli : C'est un rôle local
    """

    __tablename__ = "utilisateur_role"

    # clé primaire simple : un utilisateur peut être
    # admin dans l'entreprise A et l'entreprise B
    id: int | None = Field(default=None, primary_key=True)
    id_utilisateur: int = Field(
        foreign_key="utilisateur.id", ondelete="CASCADE", index=True
    )
    id_role: int = Field(foreign_key="role.id", index=True)
    id_entreprise: int | None = Field(
        default=None, foreign_key="entreprise.id", index=True
    )


class Permission(SQLModel, table=True):
    """Référentiel des actions possibles dans l'API (ex: facture:create)."""

    __tablename__ = "permission"

    id: int | None = Field(default=None, primary_key=True)
    libelle: str = Field(unique=True, index=True, max_length=100)
    description: str | None = Field(default=None, sa_column=Column(TEXT, nullable=True))

    roles: list["Role"] = Relationship(
        back_populates="permissions", link_model=PermissionRole
    )


class Role(SQLModel, table=True):
    """Référentiel des rôles disponibles (ex: admin, comptable, gestionnaire)."""

    __tablename__ = "role"

    id: int | None = Field(default=None, primary_key=True)
    libelle: str = Field(unique=True, index=True, max_length=100)
    description: str | None = Field(default=None, sa_column=Column(TEXT, nullable=True))

    # relation Many-to-Many vers Permission
    permissions: list["Permission"] = Relationship(
        back_populates="roles", link_model=PermissionRole
    )

    # relation Many-to-Many vers Utilisateur
    utilisateurs: list["Utilisateur"] = Relationship(
        back_populates="roles", link_model=UtilisateurRole
    )


class ReinitialisationMotDePasse(SQLModel, table=True):
    """
    Token de réinitialisation de mot de passe, à usage unique et à durée de vie
    limitée.

    Le token en clair n'est jamais stocké : seul son hash SHA-256 est persisté
    (``token_hash``). L'authentification étant globale (au niveau de l'email),
    ce jeton est rattaché à l'utilisateur sans notion d'entreprise (tenant).
    """

    __tablename__ = "reinitialisation_mot_de_passe"

    id: int | None = Field(default=None, primary_key=True)
    id_utilisateur: int = Field(
        foreign_key="utilisateur.id", ondelete="CASCADE", index=True
    )
    # hash SHA-256 hexadécimal (64 caractères) du token — jamais le clair
    token_hash: str = Field(unique=True, index=True, max_length=64)
    date_expiration: datetime
    # NULL tant que le token n'a pas servi ; horodaté à la consommation
    date_utilisation: datetime | None = Field(default=None)
    date_creation: datetime = Field(default_factory=lambda: datetime.now(UTC))
