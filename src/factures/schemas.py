from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.factures.models import TypeFacture


class FactureLigneBase(BaseModel):
    """
    Propriétés de base d'une ligne de détail de facture.
    """

    designation: str = Field(
        ..., max_length=255, description="Désignation du produit ou service"
    )
    quantite: Decimal = Field(..., max_digits=10, decimal_places=3)
    unite: str | None = Field(
        default=None,
        max_length=50,
        description="Unité de mesure (ex: heure, kg, pièce)",
    )
    prix_unitaire_ht: Decimal = Field(..., max_digits=12, decimal_places=2)
    id_taux_tva: int = Field(..., description="ID du taux de TVA applicable")


class FactureLigneCreate(FactureLigneBase):
    """
    Schéma pour l'ajout d'une ligne lors
    de la création ou modification d'une facture.
    """

    ordre: int | None = Field(
        default=None, description="Ordre d'affichage (calculé automatiquement si omis)"
    )


class FactureLigneRead(FactureLigneBase):
    """
    Schéma pour la lecture d'une ligne
    de facture avec ses montants calculés.
    """

    id: int
    id_facture: int
    ordre: int

    montant_ht: Decimal
    montant_tva: Decimal
    montant_ttc: Decimal

    model_config = ConfigDict(from_attributes=True)


class FactureBase(BaseModel):
    """
    Propriétés de base d'une facture modifiables par l'utilisateur.
    """

    id_client: int | None = Field(
        default=None, description="Client destinataire de la facture"
    )
    id_document: int | None = Field(
        default=None, description="Document source si issue d'une extraction OCR"
    )

    date_emission: date | None = Field(default=None)
    date_echeance: date | None = Field(
        default=None, description="Date limite de paiement"
    )

    devise: str = Field(default="EUR", max_length=3)
    type_facture: TypeFacture = Field(default=TypeFacture.FACTURE)

    mode_paiement: str | None = Field(default=None, max_length=50)
    iban: str | None = Field(default=None, max_length=34)
    reference_commande: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(
        default=None, description="Notes internes ou mentions spécifiques"
    )


class FactureCreate(FactureBase):
    """
    Schéma pour la création initiale d'un brouillon de facture.
    Les totaux et le numéro de facture seront générés par le système.
    """

    lignes: list[FactureLigneCreate] = Field(
        ..., min_length=1, description="Liste des articles (au moins 1 requis)"
    )


class FactureUpdate(BaseModel):
    """
    Schéma pour la mise à jour d'un brouillon de facture.
    Tous les champs sont optionnels.
    """

    id_client: int | None = None
    date_emission: date | None = None
    date_echeance: date | None = None
    mode_paiement: str | None = None
    iban: str | None = None
    reference_commande: str | None = None
    notes: str | None = None

    # Si des lignes sont envoyées lors de l'update,
    # elles écraseront les anciennes.
    lignes: list[FactureLigneCreate] | None = Field(
        default=None, description="Nouvelle liste de lignes pour remplacer l'existante"
    )


class FactureRead(FactureBase):
    """
    Schéma principal pour la lecture des informations globales d'une facture.
    Idéal pour l'affichage en liste (sans le détail des lignes).
    """

    id: int
    id_entreprise: int
    id_createur: int
    numero_facture: str
    id_statut: int

    # Snapshots (historique figé)
    siret_emetteur: str | None = None
    siret_destinataire: str | None = None
    snapshot_client: dict[str, Any] | None = None

    # Totaux calculés par l'API
    total_ht: Decimal
    total_tva: Decimal
    total_ttc: Decimal

    date_creation: datetime
    date_modification: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class FactureReadWithLignes(FactureRead):
    """
    Schéma détaillé d'une facture incluant toutes ses lignes.
    Idéal pour l'affichage de la page de détail d'une facture spécifique.
    """

    lignes: list[FactureLigneRead] = Field(default_factory=list)
