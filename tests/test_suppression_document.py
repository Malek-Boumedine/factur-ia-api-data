"""Tests de la route de suppression d'un document (``DELETE /documents/{id}``).

Sans base de données ni réseau : app minimale avec le router documents,
dépendances d'auth et de tenant surchargées, session factice qui restitue des
résultats prédéfinis et trace les opérations dans l'ordre (pour vérifier que
les extractions OCR sont supprimées avant le document — FK non nullable,
leçon du bug 1451 — et que le fichier physique n'est retiré du disque
qu'après le commit). Le répertoire d'upload est redirigé vers un dossier
temporaire (monkeypatch).
"""

from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from src.auth.dependencies import get_current_user, verify_tenant_access
from src.core.database import get_session
from src.documents.models import Document, ExtractionOcr, StatutDocument
from src.documents.router import router as documents_router
from src.utilisateurs.models import Utilisateur


class _Result:
    def __init__(self, value: Any) -> None:
        self._value = value

    def first(self) -> Any:
        return self._value

    def all(self) -> Any:
        return self._value


class _FakeSession:
    """Session factice : dépile des résultats prévus et trace chaque opération
    dans l'ordre d'émission (``operations``) pour vérifier le séquencement."""

    def __init__(self, results: list[Any]) -> None:
        self._results = results
        self.statements: list[Any] = []
        self.deleted: list[Any] = []
        self.committed = False
        self.operations: list[tuple[str, Any]] = []

    async def exec(self, statement: Any) -> _Result:
        self.statements.append(statement)
        return _Result(self._results.pop(0))

    async def delete(self, obj: Any) -> None:
        self.deleted.append(obj)
        self.operations.append(("delete", obj))

    async def flush(self) -> None:
        self.operations.append(("flush", None))

    async def commit(self) -> None:
        self.committed = True
        self.operations.append(("commit", None))


def _document(nom_fichier: str = "a1b2c3.pdf") -> Document:
    return Document(
        id=5,
        id_entreprise=1,
        id_utilisateur=1,
        nom_fichier=nom_fichier,
        nom_original="facture_fournisseur.pdf",
        statut=StatutDocument.TRAITE,
    )


def _extractions() -> list[ExtractionOcr]:
    return [
        ExtractionOcr(id=11, id_document=5),
        ExtractionOcr(id=12, id_document=5),
    ]


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


async def _delete(app: FastAPI, id_document: int = 5) -> Any:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.delete(f"/documents/{id_document}")


@pytest.fixture
def upload_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirige le répertoire d'upload du router vers un dossier temporaire."""
    dossier = tmp_path / "uploads"
    dossier.mkdir()
    monkeypatch.setattr("src.documents.router.UPLOAD_DIR", dossier)
    return dossier


async def test_suppression_document_204(upload_dir: Path) -> None:
    """Document sans facture liée : 204, extractions supprimées avant le
    document (FK non nullable), flush intercalé, commit, puis fichier
    physique retiré du disque."""
    document = _document()
    extractions = _extractions()
    (upload_dir / "a1b2c3.pdf").write_bytes(b"%PDF-1.4 contenu")
    session = _FakeSession([document, None, extractions])
    response = await _delete(_app(session))

    assert response.status_code == 204
    assert response.content == b""

    # Séquencement exact : extractions → flush → document → commit
    kinds = [kind for kind, _ in session.operations]
    assert kinds == ["delete", "delete", "flush", "delete", "commit"]
    assert session.deleted[:2] == extractions
    assert session.deleted[2] is document
    assert session.committed

    # Fichier physique supprimé après le commit
    assert not (upload_dir / "a1b2c3.pdf").exists()

    # Isolation tenant dans la requête document, contrôle sur la FK directe
    # facture.id_document (celle qui bloquerait physiquement le DELETE)
    assert "id_entreprise" in str(session.statements[0])
    assert "facture" in str(session.statements[1])
    assert "id_document" in str(session.statements[1])


async def test_refus_si_brouillon_lie_409(upload_dir: Path) -> None:
    """Un brouillon référence le document : refus 409, le détail invite à
    supprimer d'abord la facture, rien n'est supprimé (ni base ni disque)."""
    (upload_dir / "a1b2c3.pdf").write_bytes(b"%PDF-1.4 contenu")
    session = _FakeSession([_document(), 42])
    response = await _delete(_app(session))

    assert response.status_code == 409
    assert "supprimez d'abord la facture" in response.json()["detail"].lower()
    assert session.deleted == []
    assert not session.committed
    assert (upload_dir / "a1b2c3.pdf").exists()


async def test_refus_si_facture_validee_409(upload_dir: Path) -> None:
    """Une facture validée référence le document : même refus 409 — le
    contrôle est indépendant du statut, une facture validée étant immuable,
    le document reste conservé comme trace pour l'audit comptable."""
    session = _FakeSession([_document(), 43])
    response = await _delete(_app(session))

    assert response.status_code == 409
    assert session.deleted == []
    assert not session.committed


async def test_document_hors_perimetre_ou_inexistant_404(upload_dir: Path) -> None:
    """Document inexistant ou d'une autre entreprise : même 404 indistinct,
    rien n'est supprimé."""
    session = _FakeSession([None])
    response = await _delete(_app(session))

    assert response.status_code == 404
    assert (
        response.json()["detail"] == "Document introuvable dans cet espace entreprise"
    )
    assert session.deleted == []


async def test_fichier_deja_absent_204(upload_dir: Path) -> None:
    """Fichier déjà disparu du disque : la suppression en base aboutit quand
    même (204) — pas d'erreur pour un fichier qu'on voulait retirer."""
    document = _document(nom_fichier="disparu.pdf")
    session = _FakeSession([document, None, []])
    response = await _delete(_app(session))

    assert response.status_code == 204
    assert session.committed
    assert session.deleted == [document]


async def test_nom_fichier_hors_repertoire_non_supprime(
    upload_dir: Path, tmp_path: Path
) -> None:
    """Path traversal : un nom_fichier corrompu en base qui sort du répertoire
    d'upload n'est jamais supprimé du disque, même après un 204 en base."""
    cible = tmp_path / "secret.txt"
    cible.write_bytes(b"donnees sensibles")
    session = _FakeSession([_document(nom_fichier="../secret.txt"), None, []])
    response = await _delete(_app(session))

    assert response.status_code == 204
    assert cible.exists()


async def test_non_authentifie_401(upload_dir: Path) -> None:
    """Sans token, la route est inaccessible (401)."""
    session = _FakeSession([])
    app = _app(session, authenticated=False)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.delete("/documents/5", headers={"X-Entreprise-Id": "1"})

    assert response.status_code == 401
    assert session.statements == []
    assert session.deleted == []
