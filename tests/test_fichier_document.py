"""Tests de la route de consultation du fichier original
(``GET /documents/{id}/fichier``).

Sans base de données ni réseau : app minimale avec le router documents,
dépendances d'auth et de tenant surchargées, session factice. Le répertoire
d'upload est redirigé vers un dossier temporaire (monkeypatch) pour servir
de vrais fichiers et vérifier le streaming, le MIME, l'isolation tenant et
la protection contre le path traversal.
"""

from pathlib import Path
from typing import Any

import pytest
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


def _document(
    nom_fichier: str, nom_original: str = "facture_fournisseur.pdf"
) -> Document:
    return Document(
        id=5,
        id_entreprise=1,
        id_utilisateur=1,
        nom_fichier=nom_fichier,
        nom_original=nom_original,
        statut=StatutDocument.TRAITE,
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
        return await client.get(f"/documents/{id_document}/fichier")


@pytest.fixture
def upload_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirige le répertoire d'upload du router vers un dossier temporaire."""
    dossier = tmp_path / "uploads"
    dossier.mkdir()
    monkeypatch.setattr("src.documents.router.UPLOAD_DIR", dossier)
    return dossier


async def test_fichier_pdf_servi_en_inline(upload_dir: Path) -> None:
    """PDF présent : servi avec le bon MIME, le nom d'origine et une
    disposition inline (consultation dans le navigateur)."""
    contenu = b"%PDF-1.4 contenu de test"
    (upload_dir / "a1b2c3.pdf").write_bytes(contenu)
    session = _FakeSession([_document("a1b2c3.pdf")])
    response = await _get(_app(session))

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert "inline" in response.headers["content-disposition"]
    assert "facture_fournisseur.pdf" in response.headers["content-disposition"]
    assert response.content == contenu

    # Isolation tenant dans la requête document
    assert "id_entreprise" in str(session.statements[0])


async def test_fichier_image_mime_png(upload_dir: Path) -> None:
    """Image PNG : le MIME est déduit de l'extension du fichier stocké."""
    (upload_dir / "img.png").write_bytes(b"\x89PNG fake")
    session = _FakeSession([_document("img.png", nom_original="scan.png")])
    response = await _get(_app(session))

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"


async def test_extension_inconnue_octet_stream(upload_dir: Path) -> None:
    """Extension inconnue : repli sur application/octet-stream."""
    (upload_dir / "brut.inconnu").write_bytes(b"donnees")
    session = _FakeSession([_document("brut.inconnu")])
    response = await _get(_app(session))

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/octet-stream"


async def test_document_inexistant_ou_hors_tenant_404(upload_dir: Path) -> None:
    """Document inexistant ou d'une autre entreprise : même 404 indistinct,
    aucun fichier servi."""
    session = _FakeSession([None])
    response = await _get(_app(session))

    assert response.status_code == 404
    assert (
        response.json()["detail"] == "Document introuvable dans cet espace entreprise"
    )


async def test_fichier_absent_du_disque_404(upload_dir: Path) -> None:
    """Enregistrement en base mais fichier disparu du disque : 404 distinct."""
    session = _FakeSession([_document("disparu.pdf")])
    response = await _get(_app(session))

    assert response.status_code == 404
    assert response.json()["detail"] == "Fichier introuvable sur le serveur"


async def test_nom_fichier_hors_repertoire_404(
    upload_dir: Path, tmp_path: Path
) -> None:
    """Path traversal : un nom_fichier corrompu en base qui sort du répertoire
    d'upload est refusé, même si le fichier visé existe sur le disque."""
    (tmp_path / "secret.txt").write_bytes(b"donnees sensibles")
    session = _FakeSession([_document("../secret.txt")])
    response = await _get(_app(session))

    assert response.status_code == 404
    assert response.json()["detail"] == "Fichier introuvable sur le serveur"


async def test_non_authentifie_401(upload_dir: Path) -> None:
    """Sans token, la route est inaccessible (401)."""
    session = _FakeSession([])
    app = _app(session, authenticated=False)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/documents/5/fichier", headers={"X-Entreprise-Id": "1"}
        )

    assert response.status_code == 401
    assert session.statements == []
