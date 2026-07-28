"""Tests de la contrainte d'unicité composite (id_entreprise, numero_facture).

Contrairement aux autres tests factures (sessions factices), ceux-ci exercent
la vraie contrainte déclarée sur le modèle ``Facture`` : une base SQLite en
mémoire est créée depuis ``SQLModel.metadata``, qui porte la
``UniqueConstraint`` composite. Deux entreprises peuvent porter le même numéro
dans leurs séries respectives ; une même entreprise ne peut pas émettre deux
fois le même numéro.
"""

from collections.abc import Iterator
from decimal import Decimal

# L'import de tous les modules de modèles (comme dans migrations/env.py) est
# nécessaire pour que SQLModel.metadata contienne les tables référencées par
# les clés étrangères de Facture.
import pytest
import src.abonnements.models  # noqa: F401
import src.audit.models  # noqa: F401
import src.auth.models  # noqa: F401
import src.catalogue_produits.models  # noqa: F401
import src.clients.models  # noqa: F401
import src.documents.models  # noqa: F401
import src.entreprises.models  # noqa: F401
import src.notifications.models  # noqa: F401
import src.pdp.models  # noqa: F401
import src.relances.models  # noqa: F401
import src.utilisateurs.models  # noqa: F401
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, create_engine, select
from src.factures.models import Facture


@pytest.fixture
def engine() -> Iterator[Engine]:
    """Base SQLite en mémoire avec le schéma complet des modèles."""
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    yield engine
    engine.dispose()


def _make_facture(id_entreprise: int, numero_facture: str) -> Facture:
    # SQLite n'applique pas les FK par défaut : les identifiants liés sont
    # arbitraires, seul l'objet du test est la contrainte d'unicité.
    return Facture(
        id_entreprise=id_entreprise,
        id_createur=1,
        numero_facture=numero_facture,
        id_statut=1,
        total_ht=Decimal("100.00"),
        total_tva=Decimal("20.00"),
        total_ttc=Decimal("120.00"),
    )


def test_meme_numero_pour_deux_entreprises_autorise(engine: Engine) -> None:
    """Deux entreprises peuvent porter le même numéro dans leurs séries."""
    with Session(engine) as session:
        session.add(_make_facture(id_entreprise=1, numero_facture="FAC-202607-0001"))
        session.add(_make_facture(id_entreprise=2, numero_facture="FAC-202607-0001"))
        session.commit()

        factures = session.exec(select(Facture)).all()
        assert len(factures) == 2


def test_meme_numero_pour_meme_entreprise_refuse(engine: Engine) -> None:
    """Une même entreprise ne peut pas émettre deux fois le même numéro."""
    with Session(engine) as session:
        session.add(_make_facture(id_entreprise=1, numero_facture="FAC-202607-0001"))
        session.commit()

        session.add(_make_facture(id_entreprise=1, numero_facture="FAC-202607-0001"))
        with pytest.raises(IntegrityError):
            session.commit()


def test_numeros_differents_pour_meme_entreprise_autorises(engine: Engine) -> None:
    """La série d'une entreprise reste utilisable : numéros distincts acceptés."""
    with Session(engine) as session:
        session.add(_make_facture(id_entreprise=1, numero_facture="FAC-202607-0001"))
        session.add(_make_facture(id_entreprise=1, numero_facture="FAC-202607-0002"))
        session.commit()

        factures = session.exec(select(Facture)).all()
        assert len(factures) == 2
