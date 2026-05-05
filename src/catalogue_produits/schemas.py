from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from .models import TypeProduit


class CatalogueBase(BaseModel):
    """
    Propriétés communes d'un produit ou d'une prestation du catalogue,
    partagées entre les différentes requêtes API.
    """

    type_produit: TypeProduit = Field(
        default=TypeProduit.PRODUIT,
        description="Type d'élément (produit, prestation, service)",
    )
    reference: str | None = Field(
        default=None, max_length=100, description="Référence interne ou SKU du produit"
    )
    designation: str = Field(
        ...,
        max_length=255,
        description="Nom ou description courte affichée sur la facture",
    )
    prix_unitaire_ht: Decimal = Field(
        ..., ge=0, description="Prix unitaire hors taxes (doit être positif ou nul)"
    )
    unite: str | None = Field(
        default="unité",
        max_length=50,
        description="Unité de mesure (ex: heure, jour, pièce, kg)",
    )
    id_taux_tva: int = Field(
        ..., description="Clé étrangère vers la table des taux de TVA"
    )
    est_actif: bool = Field(
        default=True, description="Indique si le produit est disponible à la vente"
    )


class CatalogueCreate(CatalogueBase):
    """
    Schéma pour l'ajout d'un nouveau produit au catalogue.
    Les champs id_abonnement et id_utilisateur sont exclus ici car ils sont
    injectés de manière sécurisée par le backend via le header et le token.
    """

    pass


class CatalogueUpdate(BaseModel):
    """
    Schéma pour la mise à jour partielle d'un produit (PATCH).
    Tous les champs sont optionnels pour permettre
    de ne modifier qu'une ou plusieurs valeurs.
    """

    type_produit: TypeProduit | None = None
    reference: str | None = Field(default=None, max_length=100)
    designation: str | None = Field(default=None, max_length=255)
    prix_unitaire_ht: Decimal | None = Field(default=None, ge=0)
    unite: str | None = Field(default=None, max_length=50)
    id_taux_tva: int | None = None
    est_actif: bool | None = None


class CatalogueRead(CatalogueBase):
    """
    Schéma pour renvoyer les données du produit au front-end.
    Inclut les champs techniques générés par la base de données.
    """

    id: int
    id_abonnement: int
    id_utilisateur: int
    date_creation: datetime
    date_modification: datetime

    model_config = ConfigDict(from_attributes=True)
