from typing import TYPE_CHECKING

from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from src.utilisateurs.models import Utilisateur


class Permission(SQLModel, table=True):
    __tablename__ = "permission"

    id: int | None = Field(default=None, primary_key=True)
    libelle: str = Field(unique=True, index=True, max_length=100)
    description: str | None = Field(default=None)

    roles: list["Role"] = Relationship(
        back_populates="permissions", link_model="PermissionRole"
    )


class Role(SQLModel, table=True):
    __tablename__ = "role"

    id: int | None = Field(default=None, primary_key=True)
    libelle: str = Field(unique=True, index=True, max_length=100)
    description: str | None = Field(default=None)

    # relation Many-to-Many vers Permission
    permissions: list["Permission"] = Relationship(
        back_populates="roles", link_model="PermissionRole"
    )

    # relation Many-to-Many vers Utilisateur
    utilisateurs: list["Utilisateur"] = Relationship(
        back_populates="roles", link_model="UtilisateurRole"
    )


# tables pivot
class PermissionRole(SQLModel, table=True):
    __tablename__ = "permission_role"

    id_role: int = Field(foreign_key="role.id", primary_key=True)
    id_permission: int = Field(foreign_key="permission.id", primary_key=True)


class UtilisateurRole(SQLModel, table=True):
    __tablename__ = "utilisateur_role"

    id_utilisateur: int = Field(foreign_key="utilisateur.id", primary_key=True)
    id_role: int = Field(foreign_key="role.id", primary_key=True)
