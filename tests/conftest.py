"""Configuration commune des tests.

Chargement de l'environnement
-----------------------------
`src.core.config` instancie `Settings()` au niveau module : sans variables
d'environnement ni fichier `.env`, l'import échoue (champs requis manquants) et
la collecte pytest s'interrompt — c'est le cas en CI, où `.env` est absent.

Ce `conftest.py` est importé par pytest avant les modules de test. Il charge des
valeurs factices depuis `.env.test` **uniquement** lorsqu'aucun vrai `.env`
n'est présent : en local le `.env` réel prime et le comportement reste inchangé,
en CI les valeurs bidon permettent l'import sans exposer de secret.

Deux approches de test — règle de choix
---------------------------------------
- **Session factice** (`_FakeSession` locale au fichier de test) : logique de
  garde, permissions, routage, mapping des réponses — quand le test vérifie
  *ce que fait le code avec les résultats*.
- **Vraie base** (fixtures ci-dessous : SQLite en mémoire, schéma créé depuis
  ``SQLModel.metadata``, FK activées) : intégrité (unicité, FK, cascades), SQL
  généré, agrégations multi-lignes — quand le test vérifie *ce que la base
  répond*.

Les FK étant actives sur ``engine``, insérer d'abord le graphe de base
(fixtures ``entreprise``, ``utilisateur``, ``statuts_facture``, ``client``)
avant les objets qui le référencent — les factories de ``tests/factories.py``
pointent par défaut sur ces lignes. ``engine_sans_fk`` reste l'échappatoire
pour un test qui a de bonnes raisons d'utiliser des identifiants arbitraires.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from dotenv import load_dotenv
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# En local, un vrai `.env` existe : on n'y touche pas. En CI, il est absent : on
# fournit la config de test factice avant tout import de `src.core.config`.
if not (_PROJECT_ROOT / ".env").exists():
    load_dotenv(_PROJECT_ROOT / ".env.test")

# Les imports `src.*` (et `tests.factories`) restent après le chargement de
# l'environnement : certains modules peuvent transitivement instancier les
# Settings. L'import de tous les modules de modèles (comme dans
# migrations/env.py) est nécessaire pour que `SQLModel.metadata` soit complet.
import src.abonnements.models  # noqa: E402,F401
import src.audit.models  # noqa: E402,F401
import src.auth.models  # noqa: E402,F401
import src.catalogue_produits.models  # noqa: E402,F401
import src.clients.models  # noqa: E402,F401
import src.documents.models  # noqa: E402,F401
import src.entreprises.models  # noqa: E402,F401
import src.factures.models  # noqa: E402,F401
import src.notifications.models  # noqa: E402,F401
import src.pdp.models  # noqa: E402,F401
import src.relances.models  # noqa: E402,F401
import src.utilisateurs.models  # noqa: E402,F401
from src.clients.models import Client  # noqa: E402
from src.entreprises.models import Entreprise  # noqa: E402
from src.factures.models import StatutFacture  # noqa: E402
from src.utilisateurs.models import Utilisateur  # noqa: E402

from tests.factories import (  # noqa: E402
    STATUT_ID_PAR_LIBELLE,
    make_client,
    make_entreprise,
    make_utilisateur,
)

# ---------------------------------------------------------------------------
# Base de test partagée
# ---------------------------------------------------------------------------


def _enable_foreign_keys(dbapi_connection: Any, _connection_record: Any) -> None:
    """SQLite n'applique pas les FK par défaut : activation à chaque connexion."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def _create_sqlite_engine(*, foreign_keys: bool) -> Engine:
    engine = create_engine("sqlite://")
    if foreign_keys:
        event.listens_for(engine, "connect")(_enable_foreign_keys)
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture
def engine() -> Iterator[Engine]:
    """Base SQLite en mémoire, neuve pour chaque test, FK activées."""
    engine = _create_sqlite_engine(foreign_keys=True)
    yield engine
    engine.dispose()


@pytest.fixture
def engine_sans_fk() -> Iterator[Engine]:
    """Échappatoire : FK inactives, pour des identifiants liés arbitraires."""
    engine = _create_sqlite_engine(foreign_keys=False)
    yield engine
    engine.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    """Session synchrone sur la base du test."""
    with Session(engine) as session:
        yield session


# ---------------------------------------------------------------------------
# Graphe de données de base (référencé par les FK des objets métier)
# ---------------------------------------------------------------------------


@pytest.fixture
def entreprise(session: Session) -> Entreprise:
    """Tenant par défaut (id=1), cible des valeurs par défaut des factories."""
    entreprise = make_entreprise(id=1)
    session.add(entreprise)
    session.commit()
    return entreprise


@pytest.fixture
def autre_entreprise(session: Session) -> Entreprise:
    """Second tenant (id=2), pour les tests d'isolation inter-entreprises."""
    entreprise = make_entreprise(id=2, nom_entreprise="Autre Entreprise")
    session.add(entreprise)
    session.commit()
    return entreprise


@pytest.fixture
def utilisateur(session: Session) -> Utilisateur:
    """Créateur par défaut (id=1) des factures et clients."""
    utilisateur = make_utilisateur(id=1)
    session.add(utilisateur)
    session.commit()
    return utilisateur


@pytest.fixture
def client(
    session: Session, entreprise: Entreprise, utilisateur: Utilisateur
) -> Client:
    """Client rattaché au tenant par défaut."""
    client = make_client()
    session.add(client)
    session.commit()
    session.refresh(client)
    return client


@pytest.fixture
def statuts_facture(session: Session) -> dict[str, int]:
    """Référentiel des statuts (libellé -> id), aligné sur src/core/seed.py."""
    session.add_all(
        StatutFacture(id=id_statut, libelle=libelle)
        for libelle, id_statut in STATUT_ID_PAR_LIBELLE.items()
    )
    session.commit()
    return dict(STATUT_ID_PAR_LIBELLE)
