from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING

from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from src.abonnements.models import Abonnement
    from src.factures.models import TauxTva
    from src.utilisateurs.models import Utilisateur


class TypeProduits(str, Enum):
    ARTICLE = "article"
    PRESTATION = "prestation"


class Catalogue(SQLModel, table=True):
    __tablename__ = "catalogue"

    id: int | None = Field(default=None, primary_key=True)

    # clés étrangères
    id_abonnement: int = Field(foreign_key="abonnement.id")
    id_utilisateur: int = Field(foreign_key="utilisateur.id")
    id_taux_tva: int = Field(foreign_key="taux_tva.id")

    type_produit: TypeProduits = Field(default=TypeProduits.ARTICLE)
    reference: str | None = Field(default=None, max_length=100)
    designation: str = Field(max_length=255)

    prix_unitaire_ht: Decimal = Field(max_digits=12, decimal_places=2)
    unite: str | None = Field(default=None, max_length=50)

    est_actif: bool = Field(default=True)
    date_creation: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # --- RELATIONS ---
    abonnement: "Abonnement" = Relationship()
    createur: "Utilisateur" = Relationship()
    taux_tva: "TauxTva" = Relationship()
