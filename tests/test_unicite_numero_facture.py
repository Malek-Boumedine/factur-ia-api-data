"""Tests de la contrainte d'unicité composite (id_entreprise, numero_facture).

Contrairement aux autres tests factures (sessions factices), ceux-ci exercent
la vraie contrainte déclarée sur le modèle ``Facture`` : la base partagée de
``tests/conftest.py`` (SQLite en mémoire, FK actives) porte la
``UniqueConstraint`` composite. Deux entreprises peuvent porter le même numéro
dans leurs séries respectives ; une même entreprise ne peut pas émettre deux
fois le même numéro.
"""

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select
from src.entreprises.models import Entreprise
from src.factures.models import Facture
from src.utilisateurs.models import Utilisateur

from tests.factories import make_facture


@pytest.fixture(autouse=True)
def _graphe_de_base(
    entreprise: Entreprise,
    autre_entreprise: Entreprise,
    utilisateur: Utilisateur,
    statuts_facture: dict[str, int],
) -> None:
    """Lignes référencées par les FK (actives) de ``Facture``."""


def test_meme_numero_pour_deux_entreprises_autorise(session: Session) -> None:
    """Deux entreprises peuvent porter le même numéro dans leurs séries."""
    session.add(make_facture(id_entreprise=1, numero="FAC-202607-0001"))
    session.add(make_facture(id_entreprise=2, numero="FAC-202607-0001"))
    session.commit()

    factures = session.exec(select(Facture)).all()
    assert len(factures) == 2


def test_meme_numero_pour_meme_entreprise_refuse(session: Session) -> None:
    """Une même entreprise ne peut pas émettre deux fois le même numéro."""
    session.add(make_facture(id_entreprise=1, numero="FAC-202607-0001"))
    session.commit()

    session.add(make_facture(id_entreprise=1, numero="FAC-202607-0001"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_numeros_differents_pour_meme_entreprise_autorises(session: Session) -> None:
    """La série d'une entreprise reste utilisable : numéros distincts acceptés."""
    session.add(make_facture(id_entreprise=1, numero="FAC-202607-0001"))
    session.add(make_facture(id_entreprise=1, numero="FAC-202607-0002"))
    session.commit()

    factures = session.exec(select(Facture)).all()
    assert len(factures) == 2
