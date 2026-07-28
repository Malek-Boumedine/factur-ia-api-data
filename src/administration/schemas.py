"""
Schémas d'entrée/sortie de l'administration de plateforme.

Volontairement distincts des schémas métier (`EntrepriseRead`,
`UtilisateurRead`) : la vue administrateur agrège des informations qu'un
utilisateur normal ne doit jamais voir (compteurs de données, rattachements
inter-entreprises, état de suspension) et ignore les champs contextuels à une
entreprise active (`role`, `est_admin` du header tenant).
"""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from src.abonnements.models import StatutSouscription

# ---------------------------------------------------------------------------
# Abonnement
# ---------------------------------------------------------------------------


class SouscriptionAdminRead(BaseModel):
    """Souscription d'une entreprise, enrichie du libellé et du tarif du plan."""

    id: int
    id_abonnement: int
    libelle_abonnement: str | None = None
    tarif: Decimal | None = None
    date_debut: date
    date_fin: date | None
    statut: StatutSouscription
    date_creation: datetime

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Compteurs (pilotent les écrans de suppression côté client)
# ---------------------------------------------------------------------------


class CompteursEntreprise(BaseModel):
    """
    Volumétrie des données rattachées à une entreprise.

    `factures_scellees` compte les factures ayant quitté l'état brouillon :
    c'est ce compteur qui rend la suppression de l'entreprise définitivement
    impossible (inaltérabilité et obligation de conservation).
    """

    factures_total: int = 0
    factures_brouillon: int = 0
    factures_scellees: int = 0
    clients: int = 0
    documents: int = 0
    produits: int = 0


class CompteursUtilisateur(BaseModel):
    """
    Volumétrie des données créées par un utilisateur.

    Toute valeur non nulle interdit la suppression physique du compte : ces
    lignes portent une responsabilité nominative (qui a émis la facture) et
    sont référencées en base sans cascade.
    """

    factures_creees: int = 0
    paiements_crees: int = 0
    clients_crees: int = 0
    documents_charges: int = 0
    produits_crees: int = 0


# ---------------------------------------------------------------------------
# Entreprises
# ---------------------------------------------------------------------------


class EntrepriseAdminListItem(BaseModel):
    """Ligne de la liste des entreprises abonnées (vue administrateur)."""

    id: int
    nom_entreprise: str
    siret: str | None = None
    id_forme_juridique: int | None = None
    forme_juridique: str | None = Field(
        default=None, description="Libellé de la forme juridique (ex : SAS)."
    )
    date_creation: datetime

    est_actif: bool = Field(
        description="Faux si l'entreprise est suspendue : ses membres reçoivent "
        "alors un 403 sur toutes les routes tenant."
    )
    date_suspension: datetime | None = None
    motif_suspension: str | None = None

    souscription: SouscriptionAdminRead | None = Field(
        default=None,
        description="Souscription courante (la plus récente), quel que soit son "
        "statut — une entreprise suspendue conserve la trace de son plan.",
    )

    nombre_utilisateurs: int = 0
    nombre_utilisateurs_actifs: int = 0
    nombre_factures: int = 0


class EntrepriseAdminRead(BaseModel):
    """
    État d'une entreprise après une opération d'administration.

    Distinct d'`EntrepriseRead` (contrat des routes tenant) : il expose l'état
    de suspension, sans lequel l'administrateur ne verrait pas le résultat de
    l'action qu'il vient de déclencher.
    """

    id: int
    nom_entreprise: str
    siret: str | None = None
    id_forme_juridique: int | None = None
    date_creation: datetime
    date_modification: datetime
    est_actif: bool
    date_suspension: datetime | None = None
    motif_suspension: str | None = None

    model_config = ConfigDict(from_attributes=True)


class MembreEntrepriseRead(BaseModel):
    """Membre d'une entreprise, vu depuis l'administration de plateforme."""

    id: int
    nom: str
    prenom: str
    email: EmailStr
    est_actif: bool
    admin_plateforme: bool
    compte_protege: bool
    est_admin: bool = Field(
        description="Droit d'administration au sein de cette entreprise."
    )
    role: str | None = None
    date_derniere_connexion: datetime | None = None


class EntrepriseAdminDetail(EntrepriseAdminListItem):
    """Détail d'une entreprise : membres, historique d'abonnement, volumétrie."""

    membres: list[MembreEntrepriseRead] = Field(default_factory=list)
    souscriptions: list[SouscriptionAdminRead] = Field(
        default_factory=list,
        description="Historique complet, du plus récent au plus ancien.",
    )
    compteurs: CompteursEntreprise = Field(default_factory=CompteursEntreprise)


class EntrepriseAdminUpdate(BaseModel):
    """
    Champs d'une entreprise modifiables par un administrateur de plateforme.

    Restreint volontairement à l'identité légale. Les dates de création et de
    modification, l'état de suspension et l'abonnement ne sont pas modifiables
    ici : ils relèvent d'endpoints dédiés ou du système.
    """

    nom_entreprise: str | None = Field(default=None, min_length=1, max_length=255)
    siret: str | None = Field(
        default=None,
        min_length=14,
        max_length=14,
        description="SIRET à 14 chiffres. Ne réécrit jamais les factures déjà "
        "émises, qui en conservent un instantané figé.",
    )
    id_forme_juridique: int | None = None

    @field_validator("siret")
    @classmethod
    def _valider_siret(cls, valeur: str | None) -> str | None:
        """Vérifie que le SIRET, s'il est fourni, comporte 14 chiffres."""
        if valeur is None:
            return valeur
        if not valeur.isdigit() or len(valeur) != 14:
            raise ValueError("Le SIRET doit comporter exactement 14 chiffres.")
        return valeur


class SuspensionRequest(BaseModel):
    """Motif facultatif accompagnant la suspension d'une entreprise."""

    motif: str | None = Field(
        default=None,
        max_length=255,
        description="Raison de la suspension, conservée pour le support.",
    )


# ---------------------------------------------------------------------------
# Utilisateurs
# ---------------------------------------------------------------------------


class RattachementEntrepriseRead(BaseModel):
    """Rattachement d'un utilisateur à une entreprise."""

    id_entreprise: int
    nom_entreprise: str
    est_admin: bool
    entreprise_active: bool = Field(
        description="Faux si l'entreprise de rattachement est suspendue."
    )


class UtilisateurAdminListItem(BaseModel):
    """Ligne de la liste des utilisateurs (vue administrateur de plateforme)."""

    id: int
    nom: str
    prenom: str
    email: EmailStr
    telephone: str | None = None
    est_actif: bool
    admin_plateforme: bool
    compte_protege: bool
    date_creation: datetime
    date_derniere_connexion: datetime | None = None
    entreprises: list[RattachementEntrepriseRead] = Field(default_factory=list)


class UtilisateurAdminDetail(UtilisateurAdminListItem):
    """Détail d'un utilisateur, avec la volumétrie des données qu'il a créées."""

    compteurs: CompteursUtilisateur = Field(default_factory=CompteursUtilisateur)


# ---------------------------------------------------------------------------
# Abonnement (requêtes)
# ---------------------------------------------------------------------------


class ChangementPlanAdminRequest(BaseModel):
    """Requête de changement de plan pour une entreprise ciblée par son id."""

    id_abonnement: int = Field(description="Identifiant du plan d'abonnement cible.")
