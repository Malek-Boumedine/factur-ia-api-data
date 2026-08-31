"""Tests des sondes de disponibilité (``GET /health`` et ``GET /ready``).

Sans base de données ni réseau : l'app réelle de ``src.main`` est utilisée,
avec la dépendance de session surchargée par des sessions factices (base qui
répond, base en panne, base qui pend). ``/health`` est testée sans aucune
session injectée pour prouver son absence de dépendance. Les deux routes
sont exclues du contrat OpenAPI.
"""

import asyncio
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import OperationalError
from src.core.database import get_session
from src.main import app


class _ReadySession:
    """Session factice : la base répond au SELECT 1."""

    def __init__(self) -> None:
        self.statements: list[Any] = []

    async def execute(self, statement: Any) -> None:
        self.statements.append(statement)


class _DownSession:
    """Session factice : la base refuse la connexion."""

    async def execute(self, statement: Any) -> None:
        raise OperationalError("SELECT 1", None, Exception("connexion refusée"))


class _HangingSession:
    """Session factice : la base ne répond jamais (connexion qui pend)."""

    async def execute(self, statement: Any) -> None:
        await asyncio.sleep(30)


@pytest.fixture
def override_session() -> Iterator[Callable[[Any], None]]:
    """Surcharge `get_session` sur l'app réelle, avec nettoyage garanti."""

    def _set(session: Any) -> None:
        app.dependency_overrides[get_session] = lambda: session

    yield _set
    app.dependency_overrides.pop(get_session, None)


async def _get(path: str) -> Any:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path)


async def test_health_200_sans_base() -> None:
    """/health répond 200 sans session ni I/O : aucune surcharge de
    dépendance n'est nécessaire, la base peut être absente."""
    response = await _get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert set(body.keys()) == {"status", "app_name", "version"}


async def test_health_ne_divulgue_pas_environnement() -> None:
    """La sonde ne divulgue pas l'environnement d'exécution."""
    response = await _get("/health")

    assert "environment" not in response.json()


async def test_ready_200_quand_base_repond(
    override_session: Callable[[Any], None],
) -> None:
    """/ready répond 200 quand le SELECT 1 aboutit."""
    session = _ReadySession()
    override_session(session)

    response = await _get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
    assert "SELECT 1" in str(session.statements[0])


async def test_ready_503_quand_base_en_panne(
    override_session: Callable[[Any], None],
) -> None:
    """/ready répond 503 sur erreur de connexion, avec un corps minimal :
    aucun détail d'erreur ni trace ne fuit dans la réponse."""
    override_session(_DownSession())

    response = await _get("/ready")

    assert response.status_code == 503
    assert response.json() == {"detail": "service non prêt"}


async def test_ready_503_quand_base_pend(
    override_session: Callable[[Any], None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """/ready répond 503 quand la base dépasse le délai imparti : la sonde
    ne pend jamais (timeout réduit pour le test)."""
    override_session(_HangingSession())
    monkeypatch.setattr("src.main.READY_DB_TIMEOUT_SECONDS", 0.05)

    response = await _get("/ready")

    assert response.status_code == 503
    assert response.json() == {"detail": "service non prêt"}


def test_sondes_hors_contrat_openapi() -> None:
    """Routes d'infrastructure : exclues du schéma OpenAPI (le client généré
    côté front n'a pas à les consommer)."""
    paths = app.openapi()["paths"]

    assert "/health" not in paths
    assert "/ready" not in paths
