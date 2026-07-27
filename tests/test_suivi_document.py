"""Tests de la route de suivi d'état d'un document (``GET /documents/{id}``).

Sans base de données ni réseau : app minimale avec le router documents,
dépendances d'auth et de tenant surchargées, session factice qui restitue des
résultats prédéfinis et capture les requêtes émises (pour vérifier
structurellement l'isolation tenant et le filtre sur les extractions).
"""

from typing import Any

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from src.auth.dependencies import get_current_user, verify_tenant_access
from src.core.database import get_session
from src.documents.models import Document, StatutDocument
from src.documents.router import router as documents_router
from src.utilisateurs.models import Utilisateur


class _Result:
    def __init__(self, value: Any) -> None:
        self._value = value

    def first(self) -> Any:
        return self._value


class _FakeSession:
    """Session factice : dépile des résultats prévus et trace les requêtes."""

    def __init__(self, results: list[Any]) -> None:
        self._results = results
        self.statements: list[Any] = []

    async def exec(self, statement: Any) -> _Result:
        self.statements.append(statement)
        return _Result(self._results.pop(0))


def _document(statut: StatutDocument) -> Document:
    return Document(
        id=5,
        id_entreprise=1,
        id_utilisateur=1,
        nom_fichier="abc.pdf",
        nom_original="facture.pdf",
        statut=statut,
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


async def _get(app: FastAPI, id_document: int = 5) -> Any:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(f"/documents/{id_document}")


async def test_document_traite_expose_id_facture() -> None:
    """Document traité : statut final et id du brouillon généré par l'OCR."""
    session = _FakeSession([_document(StatutDocument.TRAITE), 77])
    response = await _get(_app(session))

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == 5
    assert body["nom_original"] == "facture.pdf"
    assert body["statut"] == "traité"
    assert body["id_facture"] == 77
    assert body["date_chargement"] is not None

    # Isolation tenant dans la requête document, filtre succès sur l'extraction
    assert "id_entreprise" in str(session.statements[0])
    assert "extraction_ocr.statut" in str(session.statements[1])


async def test_document_en_cours_sans_id_facture() -> None:
    """Pendant l'extraction : statut en_cours, pas de facture, pas de requête
    inutile sur les extractions."""
    session = _FakeSession([_document(StatutDocument.EN_COURS)])
    response = await _get(_app(session))

    assert response.status_code == 200
    body = response.json()
    assert body["statut"] == "en_cours"
    assert body["id_facture"] is None
    assert len(session.statements) == 1


async def test_document_en_erreur_sans_id_facture() -> None:
    """Extraction échouée : statut erreur, aucun id_facture ne remonte."""
    session = _FakeSession([_document(StatutDocument.ERREUR)])
    response = await _get(_app(session))

    assert response.status_code == 200
    body = response.json()
    assert body["statut"] == "erreur"
    assert body["id_facture"] is None
    assert len(session.statements) == 1


async def test_document_hors_perimetre_ou_inexistant_404() -> None:
    """Document inexistant ou d'une autre entreprise : même 404 indistinct."""
    session = _FakeSession([None])
    response = await _get(_app(session))

    assert response.status_code == 404
    assert (
        response.json()["detail"] == "Document introuvable dans cet espace entreprise"
    )


async def test_non_authentifie_401() -> None:
    """Sans token, la route est inaccessible (401)."""
    session = _FakeSession([])
    app = _app(session, authenticated=False)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/documents/5", headers={"X-Entreprise-Id": "1"})

    assert response.status_code == 401
    assert session.statements == []
