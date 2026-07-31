"""Factories des objets métier pour les tests « vraie base ».

Constructeurs purs, sans insertion : le test compose ses objets puis les
insère via la session partagée de ``tests/conftest.py``. Les identifiants par
défaut (entreprise 1, créateur 1, statut « validée ») correspondent aux
fixtures ``entreprise``, ``utilisateur`` et ``statuts_facture`` — les clés
étrangères étant actives sur le moteur partagé, insérer ce graphe de base
avant les objets qui le référencent.
"""

from datetime import date
from decimal import Decimal

from src.clients.models import Client
from src.core.seed import STATUTS_FACTURE
from src.entreprises.models import Entreprise
from src.factures.models import Facture, TypeFacture
from src.utilisateurs.models import Utilisateur

# Identifiants du référentiel des statuts, alignés sur src/core/seed.py :
# l'auto-incrément MySQL attribue 1..n dans l'ordre d'insertion du seed. La
# fixture ``statuts_facture`` insère les mêmes couples (id, libellé).
STATUT_ID_PAR_LIBELLE: dict[str, int] = {
    statut["libelle"]: position
    for position, statut in enumerate(STATUTS_FACTURE, start=1)
}

STATUT_BROUILLON = STATUT_ID_PAR_LIBELLE["brouillon"]
STATUT_VALIDEE = STATUT_ID_PAR_LIBELLE["validée"]
STATUT_PAYEE = STATUT_ID_PAR_LIBELLE["payee"]
STATUT_ANNULEE = STATUT_ID_PAR_LIBELLE["annulee"]


def make_entreprise(
    *,
    id: int | None = None,
    nom_entreprise: str = "Entreprise Test",
    siret: str | None = None,
) -> Entreprise:
    """Tenant. SIRET nul par défaut (colonne unique mais nullable)."""
    return Entreprise(id=id, nom_entreprise=nom_entreprise, siret=siret)


def make_utilisateur(
    *,
    id: int | None = None,
    email: str = "user@example.com",
) -> Utilisateur:
    """Personne physique minimale (créateur des factures et clients)."""
    return Utilisateur(
        id=id,
        nom="Test",
        prenom="User",
        email=email,
        hash_mot_de_passe="x",  # pragma: allowlist secret
    )


def make_client(
    *,
    id: int | None = None,
    id_entreprise: int = 1,
    id_createur: int = 1,
    raison_sociale: str = "Client Test",
    siret: str | None = None,
    numero_tva: str | None = None,
) -> Client:
    """Client du référentiel d'une entreprise."""
    return Client(
        id=id,
        id_entreprise=id_entreprise,
        id_createur=id_createur,
        raison_sociale=raison_sociale,
        siret=siret,
        numero_tva=numero_tva,
        code_postal="75001",
        ville="Paris",
    )


def make_facture(
    *,
    numero: str,
    id_entreprise: int = 1,
    id_createur: int = 1,
    ht: str = "100.00",
    tva: str = "20.00",
    ttc: str = "120.00",
    date_emission: date | None = None,
    id_statut: int = STATUT_VALIDEE,
    type_facture: TypeFacture = TypeFacture.FACTURE,
    id_client: int | None = None,
    devise: str = "EUR",
    date_echeance: date | None = None,
) -> Facture:
    """Facture validée par défaut ; tout est surchargeable."""
    return Facture(
        id_entreprise=id_entreprise,
        id_createur=id_createur,
        id_client=id_client,
        numero_facture=numero,
        date_emission=date_emission or date.today(),
        date_echeance=date_echeance,
        devise=devise,
        type_facture=type_facture,
        id_statut=id_statut,
        total_ht=Decimal(ht),
        total_tva=Decimal(tva),
        total_ttc=Decimal(ttc),
    )
