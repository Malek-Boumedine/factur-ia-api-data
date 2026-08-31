"""Tests des contraintes d'unicité composites du modèle ``Client``.

Chaque entreprise a son propre référentiel client : deux entreprises peuvent
facturer le même client (même SIRET, même numéro de TVA), mais une même
entreprise ne peut pas créer deux clients portant le même SIRET ou le même
numéro de TVA. Comme pour ``test_unicite_numero_facture``, la base partagée de
``tests/conftest.py`` (SQLite en mémoire, FK actives) porte les
``UniqueConstraint`` composites (id_entreprise, siret) et
(id_entreprise, numero_tva).
"""

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select
from src.clients.models import Client
from src.entreprises.models import Entreprise
from src.utilisateurs.models import Utilisateur

from tests.factories import make_client


@pytest.fixture(autouse=True)
def _graphe_de_base(
    entreprise: Entreprise,
    autre_entreprise: Entreprise,
    utilisateur: Utilisateur,
) -> None:
    """Lignes référencées par les FK (actives) de ``Client``."""


def test_meme_siret_pour_deux_entreprises_autorise(session: Session) -> None:
    """Deux entreprises peuvent référencer le même client (même SIRET)."""
    session.add(make_client(id_entreprise=1, siret="12345678900011"))
    session.add(make_client(id_entreprise=2, siret="12345678900011"))
    session.commit()

    clients = session.exec(select(Client)).all()
    assert len(clients) == 2


def test_meme_siret_pour_meme_entreprise_refuse(session: Session) -> None:
    """Une même entreprise ne peut pas avoir deux clients au même SIRET."""
    session.add(make_client(id_entreprise=1, siret="12345678900011"))
    session.commit()

    session.add(make_client(id_entreprise=1, siret="12345678900011"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_meme_numero_tva_pour_deux_entreprises_autorise(session: Session) -> None:
    """Deux entreprises peuvent référencer le même client (même numéro de TVA)."""
    session.add(make_client(id_entreprise=1, numero_tva="FR12345678901"))
    session.add(make_client(id_entreprise=2, numero_tva="FR12345678901"))
    session.commit()

    clients = session.exec(select(Client)).all()
    assert len(clients) == 2


def test_meme_numero_tva_pour_meme_entreprise_refuse(session: Session) -> None:
    """Une même entreprise ne peut pas avoir deux clients au même numéro de TVA."""
    session.add(make_client(id_entreprise=1, numero_tva="FR12345678901"))
    session.commit()

    session.add(make_client(id_entreprise=1, numero_tva="FR12345678901"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_clients_sans_siret_ni_tva_pour_meme_entreprise_autorises(
    session: Session,
) -> None:
    """Les colonnes nullables n'imposent rien : plusieurs clients sans SIRET."""
    session.add(make_client(id_entreprise=1))
    session.add(make_client(id_entreprise=1))
    session.commit()

    clients = session.exec(select(Client)).all()
    assert len(clients) == 2
