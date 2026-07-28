from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.documents.schemas import ExtractionOcrRead
from src.factures.models import Facture, TypeFacture


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


class SiretBrouillonMixin(BaseModel):
    """SIRET éditables uniquement sur le brouillon (état de travail) :
    à la validation, l'émetteur est imposé depuis l'entreprise et le
    destinataire depuis la fiche client (inaltérabilité).
    """

    siret_emetteur: str | None = Field(default=None, max_length=14)
    siret_destinataire: str | None = Field(default=None, max_length=14)

    @field_validator("siret_emetteur", "siret_destinataire", mode="before")
    @classmethod
    def normalize_siret_brouillon(cls, value: object) -> object:
        """SIRET permissif sur un brouillon : chiffres uniquement, 14 max.

        Un SIRET incomplet est accepté (état de travail) ; la vérification
        SIRENE se fait à la validation. Chaîne vide ou espaces = effacement.
        En mode ``before`` pour retirer les espaces (fréquents en OCR) avant
        le contrôle de longueur ``max_length=14``.
        """
        if not isinstance(value, str):
            return value
        value = value.replace(" ", "")
        if value == "":
            return None
        if not value.isdigit():
            raise ValueError("Le SIRET ne doit contenir que des chiffres.")
        return value


class FactureCreate(SiretBrouillonMixin, FactureBase):
    """
    Schéma pour la création initiale d'un brouillon de facture.
    Les totaux et le numéro de facture seront générés par le système.
    """

    lignes: list[FactureLigneCreate] = Field(
        ..., min_length=1, description="Liste des articles (au moins 1 requis)"
    )


class FactureUpdate(SiretBrouillonMixin):
    """
    Schéma pour la mise à jour d'un brouillon de facture (sémantique PATCH).
    Tous les champs sont optionnels : seuls les champs envoyés sont modifiés,
    un champ omis reste inchangé. Envoyer explicitement ``null`` efface un
    champ nullable.
    """

    id_client: int | None = None
    date_emission: date | None = None
    date_echeance: date | None = None
    devise: str | None = Field(default=None, max_length=3)
    type_facture: TypeFacture | None = None
    mode_paiement: str | None = Field(default=None, max_length=50)
    iban: str | None = Field(default=None, max_length=34)
    reference_commande: str | None = Field(default=None, max_length=100)
    notes: str | None = None

    # Si des lignes sont envoyées lors de l'update,
    # elles remplacent intégralement les anciennes (totaux recalculés).
    lignes: list[FactureLigneCreate] | None = Field(
        default=None,
        min_length=1,
        description="Nouvelle liste de lignes remplaçant intégralement l'existante",
    )

    @field_validator("date_emission", "devise", "type_facture")
    @classmethod
    def refuse_explicit_null(cls, value: object) -> object:
        """Champs non nullables en base : un ``null`` explicite est refusé (422)."""
        if value is None:
            raise ValueError(
                "null n'est pas accepté pour ce champ ; "
                "omettez-le pour le laisser inchangé"
            )
        return value


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
    id_facture_origine: int | None = Field(
        default=None, description="Facture d'origine si ce document est un avoir"
    )

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


class FactureListItem(FactureRead):
    """
    Élément de la liste des factures : ``FactureRead`` enrichi du nom du
    destinataire résolu, pour que le front affiche un nom sur chaque ligne
    sans requête supplémentaire.
    """

    nom_destinataire: str | None = Field(
        default=None,
        description="Raison sociale du destinataire : snapshot figé pour une "
        "facture validée, sinon client lié (brouillon)",
    )
    libelle_statut: str | None = Field(
        default=None,
        description="Libellé du statut tel que stocké dans le référentiel "
        "(ex: brouillon, validée, payee, en_retard) ; clé à mapper côté front "
        "pour l'affichage du badge. Null si le référentiel est incohérent.",
    )

    @classmethod
    def from_facture(cls, facture: Facture) -> "FactureListItem":
        """Construit l'élément de liste en résolvant le nom du destinataire
        et le libellé du statut.

        Le snapshot (données figées à la validation) est prioritaire ; à
        défaut, on lit la raison sociale du client lié (cas des brouillons).
        Les relations ``facture.client`` et ``facture.statut_ref`` doivent
        avoir été chargées en eager.
        """
        snapshot = facture.snapshot_client or {}
        nom: str | None = snapshot.get("raison_sociale")
        if not nom and facture.client is not None:
            nom = facture.client.raison_sociale
        item = cls.model_validate(facture)
        item.nom_destinataire = nom
        # Référentiel incohérent (statut orphelin) : null plutôt qu'un 500.
        statut_ref = facture.statut_ref
        item.libelle_statut = statut_ref.libelle if statut_ref is not None else None
        return item


class PeriodeStatistiques(BaseModel):
    """Période effectivement agrégée (bornes incluses)."""

    date_min: date = Field(description="Borne basse incluse sur la date d'émission.")
    date_max: date = Field(description="Borne haute incluse sur la date d'émission.")


class TotauxStatistiques(BaseModel):
    """Chiffres clés de la période, nets des avoirs."""

    ca_ht: Decimal = Field(description="Chiffre d'affaires HT net des avoirs.")
    ca_ttc: Decimal = Field(description="Chiffre d'affaires TTC net des avoirs.")
    tva_collectee: Decimal = Field(description="TVA collectée nette des avoirs.")
    nombre_factures: int = Field(
        description="Nombre de factures émises (type ``facture``, hors avoirs)."
    )
    nombre_avoirs: int = Field(description="Nombre d'avoirs émis sur la période.")
    panier_moyen: Decimal = Field(
        description="``ca_ttc`` divisé par ``nombre_factures`` (0 si aucune facture) : "
        "les avoirs pèsent sur le numérateur mais pas sur le dénominateur."
    )


class StatistiquesParStatut(BaseModel):
    """Répartition d'un statut du référentiel."""

    statut: str = Field(
        description="Libellé du statut tel que stocké dans le référentiel "
        "(ex: validée, payee, en_retard) ; clé à mapper côté front."
    )
    nombre: int = Field(description="Nombre de documents portant ce statut.")
    montant_ttc: Decimal = Field(description="Montant TTC cumulé, avoirs soustraits.")


class StatistiquesParMois(BaseModel):
    """Point mensuel de la courbe d'évolution."""

    mois: str = Field(description="Mois au format ``YYYY-MM``.")
    ca_ht: Decimal = Field(description="Chiffre d'affaires HT du mois, net des avoirs.")
    ca_ttc: Decimal = Field(
        description="Chiffre d'affaires TTC du mois, net des avoirs."
    )
    nombre: int = Field(description="Nombre de documents émis dans le mois.")


class StatistiquesParClient(BaseModel):
    """Contribution d'un client au chiffre d'affaires."""

    id_client: int | None = Field(
        default=None, description="Null pour les factures sans client rattaché."
    )
    nom_client: str | None = Field(
        default=None,
        description="Raison sociale **actuelle** du client (fiche client, pas le "
        "snapshot figé de la facture) : le regroupement se fait par identité "
        "client, pour qu'un client renommé n'apparaisse pas deux fois. Null si "
        "aucun client n'est rattaché.",
    )
    ca_ttc: Decimal = Field(description="Montant TTC cumulé, avoirs soustraits.")
    nombre: int = Field(description="Nombre de documents émis pour ce client.")


class IndicateursPaiement(BaseModel):
    """Encours client. ``montant_en_retard`` est un sous-ensemble de
    ``restant_a_encaisser`` : ne jamais additionner les deux."""

    montant_en_retard: Decimal = Field(
        description="Montant TTC des factures dont la date d'échéance est dépassée "
        "et qui ne sont ni payées ni annulées. Calculé sur ``date_echeance``, pas "
        "sur le statut ``en_retard``."
    )
    restant_a_encaisser: Decimal = Field(
        description="Montant TTC des factures émises encore dues (ni payées, ni "
        "annulées). Chiffre **pessimiste** : faute de suivi des règlements, une "
        "facture partiellement payée compte pour son total."
    )


class DeviseExclue(BaseModel):
    """Devise écartée des totaux monétaires."""

    devise: str = Field(description="Code devise ISO 4217 (ex: USD).")
    nombre: int = Field(description="Nombre de documents émis dans cette devise.")


class TotauxBrouillons(BaseModel):
    """Brouillons de la période, comptés à part du chiffre d'affaires."""

    nombre: int = Field(description="Nombre de brouillons.")
    montant_ttc: Decimal = Field(
        description="Montant TTC cumulé des brouillons, avoirs soustraits."
    )


class StatistiquesFactures(BaseModel):
    """
    Agrégations de facturation calculées en base sur une période et une devise.

    Périmètre : uniquement les documents **émis** (famille non-brouillon) de
    l'entreprise active, dans la devise demandée. Les avoirs sont soustraits
    de tous les montants, quel que soit le signe de leur stockage. Une facture
    annulée reste comptée positivement : elle se neutralise avec son avoir.
    """

    periode: PeriodeStatistiques
    devise: str = Field(
        description="Devise des montants agrégés. Les documents libellés dans une "
        "autre devise sont exclus et signalés dans ``devises_exclues``."
    )
    totaux: TotauxStatistiques
    par_statut: list[StatistiquesParStatut] = Field(
        default_factory=list, description="Répartition par statut, triée par libellé."
    )
    par_mois: list[StatistiquesParMois] = Field(
        default_factory=list,
        description="Série mensuelle continue et ordonnée couvrant toute la "
        "période : les mois sans document sont renvoyés à zéro.",
    )
    top_clients: list[StatistiquesParClient] = Field(
        default_factory=list,
        description="Clients les plus contributeurs, du CA le plus élevé au plus "
        "faible.",
    )
    paiement: IndicateursPaiement
    devises_exclues: list[DeviseExclue] = Field(
        default_factory=list,
        description="Devises présentes sur la période mais écartées des totaux "
        "(on n'additionne jamais deux devises).",
    )
    brouillons: TotauxBrouillons


class FactureReadWithLignes(FactureRead):
    """
    Schéma détaillé d'une facture incluant toutes ses lignes.
    Idéal pour l'affichage de la page de détail d'une facture spécifique.
    """

    lignes: list[FactureLigneRead] = Field(default_factory=list)

    extraction: ExtractionOcrRead | None = Field(
        default=None,
        description="Métadonnées de l'extraction OCR à l'origine de la facture "
        "(score global, type de document détecté, scores par champ). Null si la "
        "facture n'est pas issue d'un OCR ; résolu uniquement sur la route de "
        "détail (null sur les réponses de création/modification).",
    )
