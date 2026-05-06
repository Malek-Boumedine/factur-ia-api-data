from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from src.abonnements.models import StatutSouscription


class AbonnementBase(BaseModel):
    """
    Propriétés de base d'un plan d'abonnement.
    """

    libelle: str = Field(
        ..., max_length=100, description="Nom du plan (ex: Pro, Business)"
    )
    description: str | None = Field(default=None)
    tarif: Decimal = Field(default=Decimal("0"), max_digits=10, decimal_places=2)
    nombre_max_utilisateurs: int = Field(default=1)
    nombre_max_factures_mois: int = Field(default=10)


class AbonnementCreate(AbonnementBase):
    """Schéma pour la création d'un nouveau plan (Admin uniquement)."""

    pass


class AbonnementUpdate(BaseModel):
    """Schéma pour la modification d'un plan (Admin uniquement)."""

    libelle: str | None = None
    description: str | None = None
    tarif: Decimal | None = None
    nombre_max_utilisateurs: int | None = None
    nombre_max_factures_mois: int | None = None


class AbonnementRead(AbonnementBase):
    """Schéma pour la lecture d'un plan d'abonnement."""

    id: int
    model_config = ConfigDict(from_attributes=True)


# schémas pour la liaison Entreprise/Abonnement
class EntrepriseAbonnementRead(BaseModel):
    """
    Détails de la souscription d'une entreprise à un abonnement.
    """

    id: int
    id_entreprise: int
    id_abonnement: int
    date_debut: date
    date_fin: date | None
    statut: StatutSouscription
    date_creation: datetime

    model_config = ConfigDict(from_attributes=True)
