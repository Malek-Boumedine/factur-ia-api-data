"""Tests du seed des données de référence (``src/core/seed.py``).

Approche « vraie base » (SQLite async en mémoire via aiosqlite) : on vérifie
*ce que la base contient* après exécution du seed — première exécution sur base
vide, ré-exécution sans effet, cohérence des associations rôle-permission, et
résolution par libellé (jamais par identifiant numérique en dur).
"""

from collections.abc import AsyncIterator
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession
from src.abonnements.models import Abonnement
from src.auth.models import Permission, PermissionRole, Role
from src.core.seed import (
    ABONNEMENTS,
    PERMISSIONS,
    ROLE_PERMISSIONS,
    ROLES,
    STATUTS_FACTURE,
    TAUX_TVA,
    seed_reference_data,
)
from src.entreprises.models import RefFormeJuridique
from src.factures.models import StatutFacture, TauxTva
from src.notifications.models import TypeNotification
from src.pdp.models import StatutDeclaration

# ---------------------------------------------------------------------------
# Fixtures : base async en mémoire, neuve pour chaque test
# ---------------------------------------------------------------------------


@pytest.fixture
async def async_engine() -> AsyncIterator[AsyncEngine]:
    """Base SQLite async en mémoire, schéma créé depuis ``SQLModel.metadata``."""
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def async_session(async_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Session async sur la base du test."""
    async with AsyncSession(async_engine) as session:
        yield session


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SEEDED_MODELS: tuple[type[SQLModel], ...] = (
    Role,
    Permission,
    PermissionRole,
    Abonnement,
    TauxTva,
    RefFormeJuridique,
    StatutFacture,
    StatutDeclaration,
    TypeNotification,
)


async def _row_counts(session: AsyncSession) -> dict[str, int]:
    """Nombre de lignes de chaque table seedée, indexé par nom de modèle."""
    counts: dict[str, int] = {}
    for model in _SEEDED_MODELS:
        counts[model.__name__] = len((await session.exec(select(model))).all())
    return counts


async def _permissions_par_role(session: AsyncSession) -> dict[str, set[str]]:
    """Associations en base, résolues en libellés : rôle -> permissions."""
    role_par_id = {
        role.id: role.libelle for role in (await session.exec(select(Role))).all()
    }
    permission_par_id = {
        permission.id: permission.libelle
        for permission in (await session.exec(select(Permission))).all()
    }
    resultat: dict[str, set[str]] = {libelle: set() for libelle in role_par_id.values()}
    for link in (await session.exec(select(PermissionRole))).all():
        resultat[role_par_id[link.id_role]].add(permission_par_id[link.id_permission])
    return resultat


# ---------------------------------------------------------------------------
# Première exécution sur base vide
# ---------------------------------------------------------------------------


async def test_premiere_execution_cree_le_referentiel_complet(
    async_session: AsyncSession,
) -> None:
    await seed_reference_data(async_session)

    roles = (await async_session.exec(select(Role))).all()
    assert {r.libelle for r in roles} == {r["libelle"] for r in ROLES}

    permissions = (await async_session.exec(select(Permission))).all()
    assert len(permissions) == 13
    assert {p.libelle for p in permissions} == {p["libelle"] for p in PERMISSIONS}

    statuts = (await async_session.exec(select(StatutFacture))).all()
    assert len(statuts) == 12
    assert {s.libelle for s in statuts} == {s["libelle"] for s in STATUTS_FACTURE}

    taux = (await async_session.exec(select(TauxTva))).all()
    assert {t.taux for t in taux} == {Decimal(str(t["taux"])) for t in TAUX_TVA}, (
        "Les 4 taux de TVA (0, 5.5, 10, 20) doivent être seedés"
    )


async def test_premiere_execution_cree_les_cinq_abonnements(
    async_session: AsyncSession,
) -> None:
    await seed_reference_data(async_session)

    plans = {
        plan.libelle: plan
        for plan in (await async_session.exec(select(Abonnement))).all()
    }
    assert set(plans) == {"GRATUITE", "ESSENTIEL", "PRO", "BUSINESS", "ILLIMITE"}

    attendus = {
        "GRATUITE": (Decimal("0.00"), 1, 10),
        "ESSENTIEL": (Decimal("11.99"), 2, 50),
        "PRO": (Decimal("29.99"), 10, 300),
        "BUSINESS": (Decimal("79.99"), 30, 2000),
        "ILLIMITE": (Decimal("149.99"), 100, 10000),
    }
    for libelle, (tarif, max_utilisateurs, max_factures) in attendus.items():
        plan = plans[libelle]
        assert plan.tarif == tarif
        assert plan.nombre_max_utilisateurs == max_utilisateurs
        assert plan.nombre_max_factures_mois == max_factures

    # Le plan par défaut attribué à l'onboarding (résolu par libellé dans
    # src/entreprises/service.py) doit exister.
    assert "GRATUITE" in plans
    assert set(attendus) == {a["libelle"] for a in ABONNEMENTS}


# ---------------------------------------------------------------------------
# Idempotence : seconde exécution sans effet
# ---------------------------------------------------------------------------


async def test_seconde_execution_sans_effet(async_session: AsyncSession) -> None:
    await seed_reference_data(async_session)
    counts_apres_premier = await _row_counts(async_session)

    await seed_reference_data(async_session)
    counts_apres_second = await _row_counts(async_session)

    assert counts_apres_second == counts_apres_premier


async def test_relance_sur_base_partiellement_peuplee(
    async_session: AsyncSession,
) -> None:
    """Base déjà peuplée à la main, ids avec des trous : le seed complète
    les manquants sans dupliquer l'existant ni supposer d'id numérique."""
    async_session.add(Role(id=42, libelle="PROPRIETAIRE", description="pré-existant"))
    async_session.add(Permission(id=77, libelle="facture:read"))
    async_session.add(Abonnement(id=9, libelle="GRATUITE", tarif=Decimal("0.00")))
    await async_session.commit()

    await seed_reference_data(async_session)

    roles = (await async_session.exec(select(Role))).all()
    assert len([r for r in roles if r.libelle == "PROPRIETAIRE"]) == 1
    proprietaire = next(r for r in roles if r.libelle == "PROPRIETAIRE")
    assert proprietaire.id == 42, "La ligne pré-existante doit être conservée"

    permissions = (await async_session.exec(select(Permission))).all()
    assert len([p for p in permissions if p.libelle == "facture:read"]) == 1

    plans = (await async_session.exec(select(Abonnement))).all()
    assert len([p for p in plans if p.libelle == "GRATUITE"]) == 1

    # Les associations pointent sur les ids réels, pas sur des ids supposés.
    facture_read = next(p for p in permissions if p.libelle == "facture:read")
    assert facture_read.id == 77
    links = (await async_session.exec(select(PermissionRole))).all()
    assert (42, 77) in {(link.id_role, link.id_permission) for link in links}


# ---------------------------------------------------------------------------
# Cohérence des associations rôle-permission
# ---------------------------------------------------------------------------


async def test_associations_role_permission(async_session: AsyncSession) -> None:
    await seed_reference_data(async_session)

    en_base = await _permissions_par_role(async_session)

    assert en_base["PROPRIETAIRE"] == {p["libelle"] for p in PERMISSIONS}
    assert en_base["COMPTABLE"] == {
        "facture:read",
        "facture:create",
        "facture:update",
        "facture:validate",
        "client:read",
        "client:write",
    }
    assert en_base["COMMERCIAL"] == {
        "facture:read",
        "facture:create",
        "facture:update",
        "client:read",
        "client:write",
    }
    assert en_base["LECTEUR"] == {"facture:read", "client:read"}

    # Aucune association orpheline : le total en base est exactement la somme
    # des associations déclarées dans ROLE_PERMISSIONS.
    links = (await async_session.exec(select(PermissionRole))).all()
    assert len(links) == sum(len(perms) for perms in ROLE_PERMISSIONS.values())
