"""Tests de la route de lecture de l'entreprise active (``GET /entreprises/me``).

Sans base de données ni réseau : app minimale avec le router entreprises,
dépendances d'auth et de tenant surchargées, session factice qui restitue
l'entreprise attendue et trace les accès (isolation via l'id validé par la
dépendance tenant).
"""

from typing import Any

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from src.auth.dependencies import verify_tenant_access
from src.core.database import get_session
from src.entreprises.models import Entreprise
from src.entreprises.router import router as entreprises_router


class _FakeSession:
    """Session factice : sert les objets prévus par ``get`` et trace les accès."""

    def __init__(self, gets: dict[tuple[Any, Any], Any] | None = None) -> None:
        self._gets = gets or {}
        self.get_calls: list[tuple[Any, Any]] = []

    async def get(self, model: Any, key: Any) -> Any:
        self.get_calls.append((model, key))
        return self._gets.get((model, key))


def _app(session: _FakeSession, *, authenticated: bool = True) -> FastAPI:
    app = FastAPI()
    app.include_router(entreprises_router)
    app.dependency_overrides[get_session] = lambda: session
    if authenticated:
        # L'appartenance est déjà validée : la dépendance renvoie l'id du tenant.
        app.dependency_overrides[verify_tenant_access] = lambda: 1
    return app


async def _get_me(app: FastAPI) -> Any:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get("/entreprises/me", headers={"X-Entreprise-Id": "1"})


async def test_entreprise_active_renvoyee_avec_siret() -> None:
    """L'entreprise active est renvoyée au format EntrepriseRead, SIRET inclus."""
    entreprise = Entreprise(
        id=1, nom_entreprise="Mon Entreprise", siret="55217863900132"
    )
    session = _FakeSession(gets={(Entreprise, 1): entreprise})
    response = await _get_me(_app(session))

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == 1
    assert body["nom_entreprise"] == "Mon Entreprise"
    assert body["siret"] == "55217863900132"
    assert "date_creation" in body


async def test_isolation_lecture_via_id_valide_par_le_tenant() -> None:
    """La lecture utilise l'id validé par la dépendance tenant, aucun autre canal."""
    entreprise = Entreprise(id=1, nom_entreprise="Mon Entreprise", siret=None)
    session = _FakeSession(gets={(Entreprise, 1): entreprise})
    response = await _get_me(_app(session))

    assert response.status_code == 200
    # Un seul accès en base, sur l'id renvoyé par verify_tenant_access (1)
    assert session.get_calls == [(Entreprise, 1)]


async def test_entreprise_introuvable_404() -> None:
    """Lien d'appartenance présent mais entreprise absente : 404 propre."""
    session = _FakeSession(gets={})
    response = await _get_me(_app(session))

    assert response.status_code == 404
    assert response.json()["detail"] == "Entreprise introuvable."


async def test_non_authentifie_401() -> None:
    """Sans token, la route est inaccessible (401) et rien n'est lu en base."""
    session = _FakeSession(gets={})
    response = await _get_me(_app(session, authenticated=False))

    assert response.status_code == 401
    assert session.get_calls == []
