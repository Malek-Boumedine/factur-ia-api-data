"""Tests du déclenchement post-upload de l'extraction OCR.

Deux niveaux, sans base de données ni réseau :

- la tâche de fond ``dispatch_extraction`` : transitions de statut du document
  (EN_COURS si l'API IA accepte, ERREUR sinon, pas d'écrasement d'un statut
  final posé par le webhook), via une session factice et un
  ``trigger_extraction`` mocké ;
- le câblage de ``POST /documents/upload`` : la tâche de fond est bien
  planifiée avec l'id du document créé et le chemin du fichier stocké.
"""

from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from src.auth.dependencies import get_current_user, verify_tenant_access
from src.core.database import get_session
from src.documents import service
from src.documents.models import Document, StatutDocument
from src.documents.router import router as documents_router
from src.utilisateurs.models import Utilisateur

# --- Tâche de fond : dispatch_extraction ---


class _FakeSession:
    """Session factice : restitue un document et trace le commit."""

    def __init__(self, document: Document | None) -> None:
        self.document = document
        self.committed = False

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def get(self, model: type[Document], ident: int) -> Document | None:
        return self.document

    def add(self, obj: object) -> None:
        pass

    async def commit(self) -> None:
        self.committed = True


def _patch_dispatch_deps(
    monkeypatch: pytest.MonkeyPatch,
    session: _FakeSession,
    accepted: bool,
) -> None:
    """Remplace le client IA et la fabrique de session dans le service."""

    async def fake_trigger(file_path: Path, id_document: int, **kwargs: Any) -> bool:
        return accepted

    monkeypatch.setattr(service, "trigger_extraction", fake_trigger)
    monkeypatch.setattr(service, "async_session_maker", lambda: session)


def _document(statut: StatutDocument) -> Document:
    return Document(
        id=1,
        id_entreprise=1,
        id_utilisateur=1,
        nom_fichier="abc.pdf",
        nom_original="facture.pdf",
        statut=statut,
    )


async def test_acceptation_passe_le_document_en_cours(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """API IA joignable (202) : le document passe de EN_ATTENTE à EN_COURS."""
    document = _document(StatutDocument.EN_ATTENTE)
    session = _FakeSession(document)
    _patch_dispatch_deps(monkeypatch, session, accepted=True)

    await service.dispatch_extraction(1, Path("abc.pdf"))

    assert document.statut == StatutDocument.EN_COURS
    assert session.committed is True


async def test_echec_passe_le_document_en_erreur(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """API IA injoignable : le document passe en ERREUR (pas de retry MVP)."""
    document = _document(StatutDocument.EN_ATTENTE)
    session = _FakeSession(document)
    _patch_dispatch_deps(monkeypatch, session, accepted=False)

    await service.dispatch_extraction(1, Path("abc.pdf"))

    assert document.statut == StatutDocument.ERREUR
    assert session.committed is True


async def test_statut_final_du_webhook_non_ecrase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si le webhook a déjà posé TRAITE, l'acceptation ne l'écrase pas."""
    document = _document(StatutDocument.TRAITE)
    session = _FakeSession(document)
    _patch_dispatch_deps(monkeypatch, session, accepted=True)

    await service.dispatch_extraction(1, Path("abc.pdf"))

    assert document.statut == StatutDocument.TRAITE
    assert session.committed is False


async def test_document_disparu_ne_plante_pas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un document supprimé entre-temps est ignoré sans lever d'exception."""
    session = _FakeSession(document=None)
    _patch_dispatch_deps(monkeypatch, session, accepted=True)

    await service.dispatch_extraction(1, Path("abc.pdf"))

    assert session.committed is False


# --- Câblage de l'upload : la tâche de fond est planifiée ---


class _FakeUploadSession:
    """Session factice pour l'upload : simule l'attribution d'un id en base."""

    def add(self, obj: object) -> None:
        pass

    async def commit(self) -> None:
        pass

    async def refresh(self, obj: Document) -> None:
        obj.id = 123


async def test_upload_planifie_la_tache_de_fond(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """L'upload répond 202 et planifie l'extraction avec l'id et le chemin."""
    calls: list[tuple[int, Path]] = []

    async def fake_dispatch(id_document: int, file_path: Path) -> None:
        calls.append((id_document, file_path))

    monkeypatch.setattr("src.documents.router.dispatch_extraction", fake_dispatch)
    monkeypatch.setattr("src.documents.router.UPLOAD_DIR", tmp_path)

    app = FastAPI()
    app.include_router(documents_router)
    app.dependency_overrides[get_session] = lambda: _FakeUploadSession()
    app.dependency_overrides[get_current_user] = lambda: Utilisateur(
        id=1,
        nom="Test",
        prenom="User",
        email="user@example.com",
        hash_mot_de_passe="x",  # pragma: allowlist secret
    )
    app.dependency_overrides[verify_tenant_access] = lambda: 1

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/documents/upload",
            files={"file": ("facture.pdf", b"%PDF-1.4 factice", "application/pdf")},
        )

    assert response.status_code == 202
    assert response.json()["id_document"] == 123

    # La tâche de fond a tourné après la réponse, avec le fichier stocké
    assert len(calls) == 1
    id_document, file_path = calls[0]
    assert id_document == 123
    assert file_path.parent == tmp_path
    assert file_path.read_bytes() == b"%PDF-1.4 factice"
