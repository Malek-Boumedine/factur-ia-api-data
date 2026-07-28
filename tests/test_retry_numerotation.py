"""Tests du retry de numérotation lors de validations simultanées.

Deux validations concurrentes de la même entreprise peuvent calculer le même
numéro (lecture du max sans verrou) : le perdant subit une ``IntegrityError``
sur la contrainte composite au commit. Le service rejoue alors la validation
entière (rollback, relecture, numéro recalculé) jusqu'à 3 tentatives.

Sans base de données : une session factice dont le ``commit`` lève des
exceptions programmées simule la collision. Couvre le succès au 2e essai
(numéro recalculé, rollback tracé), l'épuisement des tentatives (409), la
non-retentative d'une ``IntegrityError`` étrangère à la numérotation, et le
ciblage de ``_is_collision_numero``.
"""

from decimal import Decimal
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import IntegrityError
from src.auth.dependencies import get_current_user, verify_tenant_access
from src.clients.models import Client
from src.core.database import get_session
from src.entreprises.models import Entreprise
from src.factures.models import Facture, StatutFacture
from src.factures.router import router as factures_router
from src.factures.service import _is_collision_numero
from src.utilisateurs.models import Utilisateur


class _Result:
    def __init__(self, value: Any) -> None:
        self._value = value

    def first(self) -> Any:
        return self._value


class _FakeSession:
    """Session factice : dépile des résultats prévus et des effets de commit.

    ``commit_effects`` est dépilé à chaque ``commit`` : une exception est
    levée, ``None`` fait réussir le commit. ``rollbacks`` et ``commits``
    tracent les appels pour vérifier le comportement du retry.
    """

    def __init__(
        self,
        results: list[Any],
        commit_effects: list[Exception | None],
        gets: dict[tuple[Any, Any], Any] | None = None,
    ) -> None:
        self._results = results
        self._commit_effects = commit_effects
        self._gets = gets or {}
        self.commits = 0
        self.rollbacks = 0

    async def exec(self, statement: Any) -> _Result:
        return _Result(self._results.pop(0))

    async def get(self, model: Any, key: Any) -> Any:
        return self._gets.get((model, key))

    async def commit(self) -> None:
        self.commits += 1
        effect = self._commit_effects.pop(0)
        if effect is not None:
            raise effect

    async def rollback(self) -> None:
        self.rollbacks += 1


def _facture_brouillon() -> Facture:
    facture = Facture(
        id=42,
        id_entreprise=1,
        id_createur=1,
        id_client=7,
        numero_facture="BROUILLON-42",
        id_statut=1,
        total_ht=Decimal("100.00"),
        total_tva=Decimal("20.00"),
        total_ttc=Decimal("120.00"),
    )
    facture.statut_ref = StatutFacture(id=1, libelle="Brouillon")
    facture.lignes = []
    return facture


def _referentiels() -> dict[tuple[Any, Any], Any]:
    return {
        (Entreprise, 1): Entreprise(
            id=1, nom_entreprise="Mon Entreprise", siret="99999999999999"
        ),
        (Client, 7): Client(
            id=7,
            id_entreprise=1,
            id_createur=1,
            raison_sociale="Client SA",
            siret="88888888888888",
            code_postal="75001",
            ville="Paris",
        ),
    }


def _collision_error() -> IntegrityError:
    orig = Exception(
        "(1062, \"Duplicate entry '1-FAC-202607-0005' for key "
        "'facture.unique_entreprise_numero_facture'\")"
    )
    return IntegrityError("UPDATE facture SET numero_facture = ...", {}, orig)


def _fk_error() -> IntegrityError:
    orig = Exception(
        "(1452, 'Cannot add or update a child row: a foreign key constraint fails')"
    )
    return IntegrityError("UPDATE facture SET id_client = ...", {}, orig)


def _app(session: _FakeSession) -> FastAPI:
    app = FastAPI()
    app.include_router(factures_router)
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: Utilisateur(
        id=1,
        nom="Test",
        prenom="User",
        email="user@example.com",
        hash_mot_de_passe="x",  # pragma: allowlist secret
    )
    app.dependency_overrides[verify_tenant_access] = lambda: 1
    return app


async def _valider(app: FastAPI, facture_id: int = 42) -> Any:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(f"/factures/{facture_id}/valider")


statut_validee = StatutFacture(id=2, libelle="Validée")


async def test_collision_puis_succes_au_deuxieme_essai() -> None:
    """Collision au 1er commit : rollback, relecture, numéro recalculé qui
    tient compte de la facture validée par le concurrent, succès au 2e."""
    facture = _facture_brouillon()
    session = _FakeSession(
        # 1re tentative : facture, statut, dernier numéro (le concurrent n'a
        # pas encore commité) — le commit échoue sur la contrainte composite.
        # 2e tentative : relecture, le max inclut désormais le 0005 du
        # concurrent — commit OK, puis rechargement final.
        results=[
            facture,
            statut_validee,
            "FAC-202607-0004",
            facture,
            statut_validee,
            "FAC-202607-0005",
            facture,
        ],
        commit_effects=[_collision_error(), None],
        gets=_referentiels(),
    )
    response = await _valider(_app(session))

    assert response.status_code == 200
    assert response.json()["numero_facture"] == "FAC-202607-0006"
    assert session.rollbacks == 1
    assert session.commits == 2


async def test_epuisement_des_tentatives_409() -> None:
    """Collision persistante sur les 3 tentatives : 409 explicite, pas de 500."""
    facture = _facture_brouillon()
    session = _FakeSession(
        results=[
            facture,
            statut_validee,
            "FAC-202607-0004",
            facture,
            statut_validee,
            "FAC-202607-0005",
            facture,
            statut_validee,
            "FAC-202607-0006",
        ],
        commit_effects=[_collision_error(), _collision_error(), _collision_error()],
        gets=_referentiels(),
    )
    response = await _valider(_app(session))

    assert response.status_code == 409
    assert "numérotation" in response.json()["detail"]
    assert session.commits == 3
    assert session.rollbacks == 3


async def test_integrity_error_etrangere_non_retentee() -> None:
    """Une IntegrityError sans lien avec le numéro (ex. FK) remonte telle
    quelle dès la 1re tentative : la retenter masquerait un vrai bug."""
    facture = _facture_brouillon()
    session = _FakeSession(
        results=[facture, statut_validee, "FAC-202607-0004"],
        commit_effects=[_fk_error()],
        gets=_referentiels(),
    )
    with pytest.raises(IntegrityError):
        await _valider(_app(session))

    assert session.commits == 1
    # rollback quand même effectué : la session doit rester saine
    assert session.rollbacks == 1


def test_is_collision_numero_message_mysql() -> None:
    """Le message MySQL 1062 citant la contrainte composite est reconnu."""
    assert _is_collision_numero(_collision_error()) is True


def test_is_collision_numero_message_sqlite() -> None:
    """Le message SQLite équivalent (colonnes citées) est reconnu."""
    orig = Exception(
        "UNIQUE constraint failed: facture.id_entreprise, facture.numero_facture"
    )
    exc = IntegrityError("UPDATE facture ...", {}, orig)
    assert _is_collision_numero(exc) is True


def test_is_collision_numero_rejette_fk() -> None:
    """Une erreur de clé étrangère n'est pas une collision de numérotation."""
    assert _is_collision_numero(_fk_error()) is False


def test_is_collision_numero_rejette_autre_contrainte_unique() -> None:
    """Même un doublon (1062) sur une autre contrainte unique n'est pas
    une collision de numérotation : pas de retry."""
    orig = Exception(
        "(1062, \"Duplicate entry 'x' for key 'facture.autre_contrainte'\")"
    )
    exc = IntegrityError("INSERT INTO facture ...", {}, orig)
    assert _is_collision_numero(exc) is False
