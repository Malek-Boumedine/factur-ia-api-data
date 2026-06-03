import asyncio
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

import src.abonnements.models  # noqa: F401
import src.audit.models  # noqa: F401
import src.auth.models  # noqa: F401
import src.catalogue_produits.models  # noqa: F401
import src.clients.models  # noqa: F401
import src.documents.models  # noqa: F401
import src.factures.models  # noqa: F401
import src.notifications.models  # noqa: F401
import src.pdp.models  # noqa: F401
import src.relances.models  # noqa: F401
import src.utilisateurs.models  # noqa: F401
from src.core.database import async_session_maker

# Imports spécifiques pour le seeding
from src.factures.models import StatutFacture, TauxTva
from src.notifications.models import TypeNotification
from src.pdp.models import StatutDeclaration

# ---------------------------------------------------------------------------
# Données de référence
# ---------------------------------------------------------------------------

TAUX_TVA = [
    {"taux": "0.00", "libelle": "Exonéré", "est_actif": True},
    {"taux": "5.50", "libelle": "Taux réduit", "est_actif": True},
    {"taux": "10.00", "libelle": "Taux intermédiaire", "est_actif": True},
    {"taux": "20.00", "libelle": "Taux normal", "est_actif": True},
]

STATUTS_FACTURE = [
    {"libelle": "brouillon", "description": "Facture en cours de rédaction"},
    {"libelle": "envoyée", "description": "Facture transmise au client"},
    {"libelle": "payée", "description": "Paiement reçu et confirmé"},
    {"libelle": "en_retard", "description": "Échéance dépassée sans paiement"},
    {"libelle": "annulée", "description": "Facture annulée"},
]

STATUTS_DECLARATION = [
    {"libelle": "en_attente", "description": "Déclaration créée, non encore envoyée"},
    {"libelle": "envoyée", "description": "Déclaration transmise à l'administration"},
    {"libelle": "validée", "description": "Déclaration acceptée"},
    {"libelle": "rejetée", "description": "Déclaration refusée"},
]

TYPES_NOTIFICATION = [
    {
        "libelle": "facture",
        "description": "Notification liée à une facture",
        "est_actif": True,
    },
    {
        "libelle": "relance",
        "description": "Notification de relance client",
        "est_actif": True,
    },
    {
        "libelle": "paiement",
        "description": "Notification de paiement reçu",
        "est_actif": True,
    },
    {
        "libelle": "systeme",
        "description": "Notification système ou administrative",
        "est_actif": True,
    },
]

UTILISATEUR_ADMIN = {
    "nom": "Admin",
    "prenom": "Système",
    "email": "admin@example.com",
    "mot_de_passe_hash": "<bcrypt_hash>",
    "est_actif": True,
    "est_admin": True,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _seed_table(
    session: AsyncSession, model: type, items: list[dict[str, Any]], unique_field: str
) -> None:
    """Insère les enregistrements manquants (idempotent)."""
    from sqlmodel import select

    for data in items:
        existing: Any = await session.exec(
            select(model).where(getattr(model, unique_field) == data[unique_field])
        )
        if existing.first() is None:
            session.add(model(**data))

    await session.commit()


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------


async def run_seeds() -> None:
    async with async_session_maker() as session:
        print("Seeding taux_tva...")
        await _seed_table(session, TauxTva, TAUX_TVA, "libelle")

        print("Seeding statut_facture...")
        await _seed_table(session, StatutFacture, STATUTS_FACTURE, "libelle")

        print("Seeding statut_declaration...")
        await _seed_table(session, StatutDeclaration, STATUTS_DECLARATION, "libelle")

        print("Seeding type_notification...")
        await _seed_table(session, TypeNotification, TYPES_NOTIFICATION, "libelle")

        print("✅ Seeding terminé.")


if __name__ == "__main__":
    asyncio.run(run_seeds())
