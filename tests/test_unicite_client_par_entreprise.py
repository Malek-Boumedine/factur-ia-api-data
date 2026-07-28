"""Tests des contraintes d'unicité composites du modèle ``Client``.

Chaque entreprise a son propre référentiel client : deux entreprises peuvent
facturer le même client (même SIRET, même numéro de TVA), mais une même
entreprise ne peut pas créer deux clients portant le même SIRET ou le même
numéro de TVA. Comme pour ``test_unicite_numero_facture``, une base SQLite en
mémoire est créée depuis ``SQLModel.metadata``, qui porte les
``UniqueConstraint`` composites (id_entreprise, siret) et
(id_entreprise, numero_tva).
"""

from collections.abc import Iterator

# L'import de tous les modules de modèles (comme dans migrations/env.py) est
# nécessaire pour que SQLModel.metadata contienne les tables référencées par
# les clés étrangères de Client.
import pytest
import src.abonnements.models  # noqa: F401
import src.audit.models  # noqa: F401
import src.auth.models  # noqa: F401
import src.catalogue_produits.models  # noqa: F401
import src.documents.models  # noqa: F401
import src.entreprises.models  # noqa: F401
import src.factures.models  # noqa: F401
import src.notifications.models  # noqa: F401
import src.pdp.models  # noqa: F401
import src.relances.models  # noqa: F401
import src.utilisateurs.models  # noqa: F401
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, create_engine, select
from src.clients.models import Client


@pytest.fixture
def engine() -> Iterator[Engine]:
    """Base SQLite en mémoire avec le schéma complet des modèles."""
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    yield engine
    engine.dispose()


def _make_client(
    id_entreprise: int,
    siret: str | None = None,
    numero_tva: str | None = None,
) -> Client:
    # SQLite n'applique pas les FK par défaut : les identifiants liés sont
    # arbitraires, seul l'objet du test est la contrainte d'unicité.
    return Client(
        id_entreprise=id_entreprise,
        id_createur=1,
        raison_sociale="Client Test",
        siret=siret,
        numero_tva=numero_tva,
        code_postal="75001",
        ville="Paris",
    )


def test_meme_siret_pour_deux_entreprises_autorise(engine: Engine) -> None:
    """Deux entreprises peuvent référencer le même client (même SIRET)."""
    with Session(engine) as session:
        session.add(_make_client(id_entreprise=1, siret="12345678900011"))
        session.add(_make_client(id_entreprise=2, siret="12345678900011"))
        session.commit()

        clients = session.exec(select(Client)).all()
        assert len(clients) == 2


def test_meme_siret_pour_meme_entreprise_refuse(engine: Engine) -> None:
    """Une même entreprise ne peut pas avoir deux clients au même SIRET."""
    with Session(engine) as session:
        session.add(_make_client(id_entreprise=1, siret="12345678900011"))
        session.commit()

        session.add(_make_client(id_entreprise=1, siret="12345678900011"))
        with pytest.raises(IntegrityError):
            session.commit()


def test_meme_numero_tva_pour_deux_entreprises_autorise(engine: Engine) -> None:
    """Deux entreprises peuvent référencer le même client (même numéro de TVA)."""
    with Session(engine) as session:
        session.add(_make_client(id_entreprise=1, numero_tva="FR12345678901"))
        session.add(_make_client(id_entreprise=2, numero_tva="FR12345678901"))
        session.commit()

        clients = session.exec(select(Client)).all()
        assert len(clients) == 2


def test_meme_numero_tva_pour_meme_entreprise_refuse(engine: Engine) -> None:
    """Une même entreprise ne peut pas avoir deux clients au même numéro de TVA."""
    with Session(engine) as session:
        session.add(_make_client(id_entreprise=1, numero_tva="FR12345678901"))
        session.commit()

        session.add(_make_client(id_entreprise=1, numero_tva="FR12345678901"))
        with pytest.raises(IntegrityError):
            session.commit()


def test_clients_sans_siret_ni_tva_pour_meme_entreprise_autorises(
    engine: Engine,
) -> None:
    """Les colonnes nullables n'imposent rien : plusieurs clients sans SIRET."""
    with Session(engine) as session:
        session.add(_make_client(id_entreprise=1))
        session.add(_make_client(id_entreprise=1))
        session.commit()

        clients = session.exec(select(Client)).all()
        assert len(clients) == 2
