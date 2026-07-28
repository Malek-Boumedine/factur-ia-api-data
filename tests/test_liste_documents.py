"""Tests de la route de liste des documents (``GET /documents/``).

Sans base de données ni réseau : app minimale avec le router documents,
dépendances d'auth et de tenant surchargées, session factice qui restitue
des résultats prédéfinis (comptage puis page) et capture les requêtes pour
vérifier structurellement le filtre par statut, le tri, la pagination et
l'isolation tenant.
"""

from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from src.auth.dependencies import get_current_user, verify_tenant_access
from src.core.database import get_session
from src.documents.models import (
    Document,
    ExtractionOcr,
    StatutDocument,
    StatutExtraction,
)
from src.documents.router import router as documents_router
from src.utilisateurs.models import Utilisateur


class _Result:
    def __init__(self, value: Any) -> None:
        self._value = value

    def one(self) -> Any:
        return self._value

    def all(self) -> Any:
        return self._value


class _FakeSession:
    """Session factice : dépile des résultats prévus et trace les requêtes."""

    def __init__(self, results: list[Any]) -> None:
        self._results = results
        self.statements: list[Any] = []

    async def exec(self, statement: Any) -> _Result:
        self.statements.append(statement)
        return _Result(self._results.pop(0))


def _document(
    id_document: int,
    statut: StatutDocument,
    extractions: list[ExtractionOcr] | None = None,
) -> Document:
    document = Document(
        id=id_document,
        id_entreprise=1,
        id_utilisateur=1,
        nom_fichier=f"{id_document}.pdf",
        nom_original=f"facture_{id_document}.pdf",
        statut=statut,
        date_chargement=datetime(2026, 7, 20, 12, 0, tzinfo=UTC),
    )
    document.extractions = extractions or []
    return document


def _traite_avec_historique() -> Document:
    """Document traité avec un historique d'extractions : un échec, puis deux
    succès — seul le succès le plus récent porte l'id_facture attendu."""
    return _document(
        5,
        StatutDocument.TRAITE,
        extractions=[
            ExtractionOcr(
                id=1,
                id_document=5,
                statut=StatutExtraction.ECHEC,
                date_extraction=datetime(2026, 7, 20, 12, 5, tzinfo=UTC),
            ),
            ExtractionOcr(
                id=2,
                id_document=5,
                statut=StatutExtraction.SUCCES,
                id_facture=70,
                date_extraction=datetime(2026, 7, 20, 12, 10, tzinfo=UTC),
            ),
            ExtractionOcr(
                id=3,
                id_document=5,
                statut=StatutExtraction.SUCCES,
                id_facture=77,
                date_extraction=datetime(2026, 7, 20, 12, 15, tzinfo=UTC),
            ),
        ],
    )


def _app(session: _FakeSession, *, authenticated: bool = True) -> FastAPI:
    app = FastAPI()
    app.include_router(documents_router)
    app.dependency_overrides[get_session] = lambda: session
    if authenticated:
        app.dependency_overrides[get_current_user] = lambda: Utilisateur(
            id=1,
            nom="Test",
            prenom="User",
            email="user@example.com",
            hash_mot_de_passe="x",  # pragma: allowlist secret
        )
        app.dependency_overrides[verify_tenant_access] = lambda: 1
    return app


async def _get(app: FastAPI, params: dict[str, Any] | None = None) -> Any:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get("/documents/", params=params or {})


def _bound_params(statement: Any) -> list[Any]:
    return list(statement.compile().params.values())


async def test_liste_mixte_id_facture_resolu() -> None:
    """Documents traité et en cours ensemble : l'id_facture du traité vient de
    l'extraction réussie la plus récente, celui de l'en cours reste null."""
    session = _FakeSession(
        [2, [_traite_avec_historique(), _document(6, StatutDocument.EN_COURS)]]
    )
    response = await _get(_app(session))

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert body["skip"] == 0
    assert body["limit"] == 100
    assert len(body["items"]) == 2

    traite, en_cours = body["items"]
    assert traite["id"] == 5
    assert traite["nom_original"] == "facture_5.pdf"
    assert traite["statut"] == "traité"
    assert traite["id_facture"] == 77
    assert traite["date_chargement"] is not None
    assert en_cours["statut"] == "en_cours"
    assert en_cours["id_facture"] is None

    # Isolation tenant dans le comptage et dans la page
    assert "id_entreprise" in str(session.statements[0])
    assert "id_entreprise" in str(session.statements[1])


async def test_document_traite_sans_extraction_reussie() -> None:
    """Document traité mais sans extraction en succès (donnée incohérente) :
    id_facture reste null, pas d'erreur."""
    document = _document(
        9,
        StatutDocument.TRAITE,
        extractions=[ExtractionOcr(id=1, id_document=9, statut=StatutExtraction.ECHEC)],
    )
    session = _FakeSession([1, [document]])
    response = await _get(_app(session))

    assert response.status_code == 200
    assert response.json()["items"][0]["id_facture"] is None


async def test_filtre_statut() -> None:
    """?statut=traité : filtre appliqué au comptage ET à la page (total
    cohérent avec la liste affichée)."""
    session = _FakeSession([1, [_traite_avec_historique()]])
    response = await _get(_app(session), {"statut": "traité"})

    assert response.status_code == 200
    assert StatutDocument.TRAITE in _bound_params(session.statements[0])
    assert StatutDocument.TRAITE in _bound_params(session.statements[1])


async def test_filtre_statut_invalide_422() -> None:
    """Statut hors enum : rejeté avant toute requête."""
    session = _FakeSession([])
    response = await _get(_app(session), {"statut": "inconnu"})

    assert response.status_code == 422
    assert session.statements == []


async def test_pagination() -> None:
    """skip/limit découpent la page filtrée, l'enveloppe reflète le total."""
    session = _FakeSession([12, [_document(6, StatutDocument.EN_ATTENTE)]])
    response = await _get(_app(session), {"skip": 10, "limit": 2})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 12
    assert body["skip"] == 10
    assert body["limit"] == 2

    page_params = _bound_params(session.statements[1])
    assert 10 in page_params
    assert 2 in page_params


async def test_tri_plus_recents_d_abord() -> None:
    """Tri par date de chargement décroissante, id décroissant en départage."""
    session = _FakeSession([0, []])
    response = await _get(_app(session))

    assert response.status_code == 200
    assert "ORDER BY document.date_chargement DESC, document.id DESC" in str(
        session.statements[1]
    )


async def test_limit_hors_bornes_422() -> None:
    """limit au-delà du plafond : rejeté avant toute requête."""
    session = _FakeSession([])
    response = await _get(_app(session), {"limit": 1000})

    assert response.status_code == 422
    assert session.statements == []


async def test_non_authentifie_401() -> None:
    """Sans token, la route est inaccessible (401)."""
    session = _FakeSession([])
    app = _app(session, authenticated=False)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/documents/", headers={"X-Entreprise-Id": "1"})

    assert response.status_code == 401
    assert session.statements == []
