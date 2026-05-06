from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import Column, DateTime, Numeric
from sqlmodel import Field, Relationship, SQLModel

from src.factures.models import TauxTva

if TYPE_CHECKING:
    from src.abonnements.models import Abonnement
    from src.utilisateurs.models import Utilisateur


# type de produits pour les auto entrepreneurs
class TypeProduit(str, Enum):
    PRODUIT = "produit"  # Vente de marchandises
    PRESTATION = "prestation"  # Prestations de services
    SERVICE = "service"  # Autres types de services / BNC


# # type de produits pour tous types de sociétés
# class TypeProduit(str, Enum):
#     BIEN = "bien"               # Chose physique
#     SERVICE = "service"         # Travail immatériel
#     ABONNEMENT = "abonnement"   # Revenu récurrent


class Catalogue(SQLModel, table=True):
    __tablename__ = "catalogue_produits"

    id: int | None = Field(default=None, primary_key=True)

    # Clés étrangères
    id_abonnement: int = Field(foreign_key="abonnement.id", index=True)
    id_utilisateur: int = Field(foreign_key="utilisateur.id")
    id_taux_tva: int = Field(foreign_key="taux_tva.id")

    type_produit: TypeProduit = Field(default=TypeProduit.PRODUIT)
    reference: str | None = Field(default=None, max_length=100, index=True)
    designation: str = Field(max_length=255)

    # Utilisation de Numeric pour la précision financière
    prix_unitaire_ht: Decimal = Field(
        sa_column=Column(Numeric(precision=12, scale=2), nullable=False)
    )
    unite: str | None = Field(default="unité", max_length=50)

    est_actif: bool = Field(default=True)

    date_creation: datetime = Field(default_factory=lambda: datetime.now(UTC))
    date_modification: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), onupdate=lambda: datetime.now(UTC)),
    )

    # --- RELATIONS ---
    abonnement: "Abonnement" = Relationship()
    createur: "Utilisateur" = Relationship()
    taux_tva: "TauxTva" = Relationship()
