import asyncio
from decimal import Decimal
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

# Imports spécifiques pour le seeding
from src.abonnements.models import Abonnement
from src.auth.models import Permission, PermissionRole, Role
from src.core.database import async_session_maker
from src.entreprises.models import RefFormeJuridique
from src.factures.models import StatutFacture, TauxTva
from src.notifications.models import TypeNotification
from src.pdp.models import StatutDeclaration

# ---------------------------------------------------------------------------
# Données de référence
# ---------------------------------------------------------------------------
ROLES = [
    {
        "libelle": "PROPRIETAIRE",
        "description": "Administrateur (Propriétaire / Gérant) — \
            Accès total à toutes les ressources de l'entreprise.",
    },
    {
        "libelle": "COMPTABLE",
        "description": "Gestion de la facturation — \
            Accès complet aux factures, avoirs et clients.",
    },
    {
        "libelle": "COMMERCIAL",
        "description": "Gestion commerciale — \
            Création de brouillons et fiches clients. Pas de validation.",
    },
    {
        "libelle": "LECTEUR",
        "description": "Consultant ou invité externe — \
            Lecture seule sur les documents et les clients.",
    },
]

PERMISSIONS = [
    {"libelle": "facture:read", "description": "Voir les factures"},
    {"libelle": "facture:create", "description": "Créer des brouillons de factures"},
    {"libelle": "facture:update", "description": "Modifier des brouillons"},
    {"libelle": "facture:validate", "description": "Valider des factures"},
    {"libelle": "client:read", "description": "Consulter les clients"},
    {"libelle": "client:write", "description": "Gérer les clients"},
    {"libelle": "users:read", "description": "Consulter les membres de l'équipe"},
    {"libelle": "users:create", "description": "Créer un membre de l'équipe"},
    {"libelle": "users:delete", "description": "Supprimer un membre de l'équipe"},
    {"libelle": "users:update", "description": "Modifier un membre de l'équipe"},
    {"libelle": "client:create", "description": "Créer un client"},
    {"libelle": "client:update", "description": "Modifier un client"},
    {"libelle": "client:delete", "description": "Supprimer un client"},
]

# Associations rôle → permissions, par libellé (jamais par id numérique : les
# identifiants diffèrent d'un environnement à l'autre).
ROLE_PERMISSIONS: dict[str, list[str]] = {
    "PROPRIETAIRE": [p["libelle"] for p in PERMISSIONS],
    "COMPTABLE": [
        "facture:read",
        "facture:create",
        "facture:update",
        "facture:validate",
        "client:read",
        "client:write",
    ],
    "COMMERCIAL": [
        "facture:read",
        "facture:create",
        "facture:update",
        "client:read",
        "client:write",
    ],
    "LECTEUR": ["facture:read", "client:read"],
}

ABONNEMENTS = [
    {
        "libelle": "GRATUITE",
        "description": "Plan gratuit par défaut attribué à toute nouvelle "
        "entreprise lors de l'onboarding.",
        "tarif": Decimal("0.00"),
        "nombre_max_utilisateurs": 1,
        "nombre_max_factures_mois": 10,
    },
    {
        "libelle": "ESSENTIEL",
        "description": "Pour les indépendants et micro-entrepreneurs qui "
        "facturent régulièrement.",
        "tarif": Decimal("11.99"),
        "nombre_max_utilisateurs": 2,
        "nombre_max_factures_mois": 50,
    },
    {
        "libelle": "PRO",
        "description": "Pour les TPE et petites équipes qui gèrent un volume "
        "de facturation soutenu.",
        "tarif": Decimal("29.99"),
        "nombre_max_utilisateurs": 10,
        "nombre_max_factures_mois": 300,
    },
    {
        "libelle": "BUSINESS",
        "description": "Pour les PME avec plusieurs collaborateurs et un fort "
        "volume de factures.",
        "tarif": Decimal("79.99"),
        "nombre_max_utilisateurs": 30,
        "nombre_max_factures_mois": 2000,
    },
    {
        "libelle": "ILLIMITE",
        "description": "Plan avec un nombre de factures illimité",
        "tarif": Decimal("149.99"),
        "nombre_max_utilisateurs": 100,
        "nombre_max_factures_mois": 10000,
    },
]

TAUX_TVA = [
    {"taux": "0.00", "libelle": "Exonéré", "est_actif": True},
    {"taux": "5.50", "libelle": "Taux réduit", "est_actif": True},
    {"taux": "10.00", "libelle": "Taux intermédiaire", "est_actif": True},
    {"taux": "20.00", "libelle": "Taux normal", "est_actif": True},
]

# Formes juridiques courantes des TPE/PME françaises. Le `code` est
# l'abréviation usuelle stable (clé d'idempotence du seed).
FORMES_JURIDIQUES = [
    {"code": "EI", "libelle": "Entreprise individuelle"},
    {
        "code": "MICRO",
        "libelle": "Micro-entreprise",
        "mention_tva_defaut": "TVA non applicable, art. 293 B du CGI",
    },
    {"code": "EURL", "libelle": "Entreprise unipersonnelle à responsabilité limitée"},
    {"code": "SARL", "libelle": "Société à responsabilité limitée"},
    {"code": "SASU", "libelle": "Société par actions simplifiée unipersonnelle"},
    {"code": "SAS", "libelle": "Société par actions simplifiée"},
    {"code": "SA", "libelle": "Société anonyme"},
    {"code": "SNC", "libelle": "Société en nom collectif"},
    {"code": "SCI", "libelle": "Société civile immobilière"},
    {"code": "ASSO", "libelle": "Association loi 1901"},
]


STATUTS_FACTURE = [
    {
        "libelle": "brouillon",
        "description": "Facture en cours de rédaction ou issue de l'OCR.",
    },
    {"libelle": "validée", "description": "Facture scellée et inaltérable."},
    {"libelle": "en_attente_pdp", "description": "En attente d'envoi vers la PDP."},
    {
        "libelle": "erreur_transmission",
        "description": "Échec technique de l'envoi à la PDP.",
    },
    {"libelle": "deposee_pdp", "description": "Dépôt réussi sur la plateforme PDP."},
    {
        "libelle": "rejetee_pdp",
        "description": "Rejet métier par la PDP (ex: SIRET invalide).",
    },
    {"libelle": "envoyee_client", "description": "Transmise directement au client."},
    {"libelle": "en_retard", "description": "La date d'échéance est dépassée."},
    {"libelle": "partiellement_payee", "description": "Paiement partiel reçu."},
    {"libelle": "payee", "description": "Intégralement réglée."},
    {"libelle": "contestee", "description": "Mise en litige par le client."},
    {"libelle": "annulee", "description": "Annulée par un avoir."},
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _seed_table(
    session: AsyncSession, model: type, items: list[dict[str, Any]], unique_field: str
) -> None:
    """
    Insère les enregistrements manquants (idempotent).

    L'existence est d'abord testée sur `unique_field`. L'insertion se fait
    ensuite dans un SAVEPOINT : si la ligne existe déjà sous une *autre*
    contrainte d'unicité (ex : `taux_tva.taux` alors qu'on filtre sur
    `libelle`), le doublon est ignoré silencieusement sans invalider les
    autres insertions du lot.
    """
    from sqlalchemy.exc import IntegrityError
    from sqlmodel import select

    for data in items:
        existing: Any = await session.exec(
            select(model).where(getattr(model, unique_field) == data[unique_field])
        )
        if existing.first() is not None:
            continue

        try:
            async with session.begin_nested():
                session.add(model(**data))
        except IntegrityError:
            # Déjà présent sous une autre clé unique → on ignore.
            pass

    await session.commit()


async def _seed_role_permissions(session: AsyncSession) -> None:
    """
    Associe les rôles à leurs permissions selon `ROLE_PERMISSIONS` (idempotent).

    Les rôles et permissions sont résolus par libellé — jamais par identifiant
    numérique, les ids variant d'un environnement à l'autre. Les associations
    déjà présentes sont conservées telles quelles ; seules les manquantes sont
    insérées. Un libellé introuvable est une erreur de configuration du seed :
    on échoue explicitement plutôt que de laisser un rôle incomplet en silence.
    """
    from sqlmodel import select

    role_ids = {
        role.libelle: role.id
        for role in (await session.exec(select(Role))).all()
        if role.id is not None
    }
    permission_ids = {
        permission.libelle: permission.id
        for permission in (await session.exec(select(Permission))).all()
        if permission.id is not None
    }
    existing_links = {
        (link.id_role, link.id_permission)
        for link in (await session.exec(select(PermissionRole))).all()
    }

    for role_libelle, permission_libelles in ROLE_PERMISSIONS.items():
        id_role = role_ids.get(role_libelle)
        if id_role is None:
            raise RuntimeError(f"Seed incohérent : rôle '{role_libelle}' introuvable.")
        for permission_libelle in permission_libelles:
            id_permission = permission_ids.get(permission_libelle)
            if id_permission is None:
                raise RuntimeError(
                    f"Seed incohérent : permission '{permission_libelle}' introuvable."
                )
            if (id_role, id_permission) not in existing_links:
                session.add(
                    PermissionRole(id_role=id_role, id_permission=id_permission)
                )

    await session.commit()


async def _seed_admin_plateforme(session: AsyncSession) -> None:
    """
    Seed idempotent du premier administrateur de plateforme (compte racine).

    Les identifiants proviennent des variables d'environnement
    (`PLATFORM_ADMIN_EMAIL` / `PLATFORM_ADMIN_PASSWORD`) — jamais en dur. Si
    l'une des deux est absente, le seed est ignoré sans bloquer le démarrage.

    Le compte est créé avec `admin_plateforme=True` et `compte_protege=True`
    (non-supprimable, non-révocable). Si l'email existe déjà, on garantit
    seulement le statut admin plateforme sans toucher au mot de passe.
    """
    from sqlmodel import select

    from src.core.config import settings
    from src.core.security import get_password_hash
    from src.utilisateurs.models import Utilisateur

    email = settings.PLATFORM_ADMIN_EMAIL
    password = settings.PLATFORM_ADMIN_PASSWORD
    if not email or not password:
        print(
            "⚠️  Seed admin plateforme ignoré "
            "(PLATFORM_ADMIN_EMAIL / PLATFORM_ADMIN_PASSWORD non définis)."
        )
        return

    existing = (
        await session.exec(select(Utilisateur).where(Utilisateur.email == email))
    ).first()

    if existing is None:
        session.add(
            Utilisateur(
                nom=settings.PLATFORM_ADMIN_NOM,
                prenom=settings.PLATFORM_ADMIN_PRENOM,
                email=email,
                hash_mot_de_passe=get_password_hash(password),
                est_actif=True,
                admin_plateforme=True,
                compte_protege=True,
            )
        )
    elif not existing.admin_plateforme or not existing.compte_protege:
        # on garantit le statut sans réécrire le mot de passe.
        existing.admin_plateforme = True
        existing.compte_protege = True
        session.add(existing)

    await session.commit()


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------


async def seed_reference_data(session: AsyncSession) -> None:
    """Seed idempotent des données de référence (hors admin plateforme)."""
    print("🌱 Seeding roles...")
    await _seed_table(session, Role, ROLES, "libelle")

    print("🌱 Seeding permissions...")
    await _seed_table(session, Permission, PERMISSIONS, "libelle")

    print("🌱 Seeding permission_role...")
    await _seed_role_permissions(session)

    print("🌱 Seeding abonnements...")
    await _seed_table(session, Abonnement, ABONNEMENTS, "libelle")

    print("🌱 Seeding taux_tva...")
    await _seed_table(session, TauxTva, TAUX_TVA, "libelle")

    print("🌱 Seeding ref_forme_juridique...")
    await _seed_table(session, RefFormeJuridique, FORMES_JURIDIQUES, "code")

    print("🌱 Seeding statut_facture...")
    await _seed_table(session, StatutFacture, STATUTS_FACTURE, "libelle")

    print("🌱 Seeding statut_declaration...")
    await _seed_table(session, StatutDeclaration, STATUTS_DECLARATION, "libelle")

    print("🌱 Seeding type_notification...")
    await _seed_table(session, TypeNotification, TYPES_NOTIFICATION, "libelle")


async def run_seeds() -> None:
    async with async_session_maker() as session:
        await seed_reference_data(session)

        print("🌱 Seeding admin plateforme...")
        await _seed_admin_plateforme(session)

        print("✅ Seeding terminé.")


if __name__ == "__main__":
    asyncio.run(run_seeds())
