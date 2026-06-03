from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Column, DateTime
from sqlmodel import Field, Relationship, SQLModel, UniqueConstraint

from src.abonnements.models import EntrepriseAbonnement

if TYPE_CHECKING:
    from src.abonnements.models import Abonnement
    from src.utilisateurs.models import Utilisateur


class RefFormeJuridique(SQLModel, table=True):
    """Référentiel des formes juridiques (SAS, SARL, Auto-entreprise...)"""

    __tablename__ = "ref_forme_juridique"

    id: int | None = Field(default=None, primary_key=True)
    code: str = Field(unique=True, index=True, max_length=20)
    libelle: str = Field(max_length=100)
    mention_tva_defaut: str | None = Field(default=None, max_length=255)
    est_actif: bool = Field(default=True)


class UtilisateurEntreprise(SQLModel, table=True):
    """Table pivot : Lie un utilisateur \
        à une ou plusieurs entreprises (multi-tenancy)
    """

    __tablename__ = "utilisateur_entreprise"
    __table_args__ = (
        UniqueConstraint(
            "id_utilisateur", "id_entreprise", name="unique_utilisateur_entreprise"
        ),
    )

    id_utilisateur: int = Field(foreign_key="utilisateur.id", primary_key=True)
    id_entreprise: int = Field(foreign_key="entreprise.id", primary_key=True)

    est_admin: bool = Field(default=False)


class Entreprise(SQLModel, table=True):
    """Entité centrale du SaaS (Le Tenant)"""

    __tablename__ = "entreprise"

    id: int | None = Field(default=None, primary_key=True)
    nom_entreprise: str = Field(max_length=255, index=True)
    siret: str | None = Field(default=None, max_length=14, unique=True, index=True)

    id_forme_juridique: int | None = Field(
        default=None, foreign_key="ref_forme_juridique.id"
    )

    date_creation: datetime = Field(default_factory=lambda: datetime.now(UTC))
    date_modification: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), onupdate=lambda: datetime.now(UTC)),
    )

    # relations
    forme_juridique: RefFormeJuridique | None = Relationship()

    abonnements: list["Abonnement"] = Relationship(
        back_populates="entreprises", link_model=EntrepriseAbonnement
    )
    utilisateurs: list["Utilisateur"] = Relationship(
        back_populates="entreprises", link_model=UtilisateurEntreprise
    )
