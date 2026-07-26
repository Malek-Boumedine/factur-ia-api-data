"""Tests des garde-fous de transition d'état des factures.

Sans base de données ni réseau : mêmes doublures que les autres tests factures.
Couvre les refus de ``POST /valider`` (facture non-brouillon, brouillon
incomplet sans client) et de ``POST /avoir`` (facture source non validée),
tous alignés sur 409, plus le 404 hors périmètre.
"""

from decimal import Decimal
from typing import Any

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from src.auth.dependencies import get_current_user, verify_tenant_access
from src.core.database import get_session
from src.factures.models import Facture, StatutFacture
from src.factures.router import router as factures_router
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


def _facture(statut: str, id_client: int | None) -> Facture:
    facture = Facture(
        id=42,
        id_entreprise=1,
        id_createur=1,
        id_client=id_client,
        numero_facture="BROUILLON-42",
        id_statut=1,
        total_ht=Decimal("100.00"),
        total_tva=Decimal("20.00"),
        total_ttc=Decimal("120.00"),
    )
    facture.statut_ref = StatutFacture(id=1, libelle=statut)
    return facture


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


async def test_valider_facture_non_brouillon_409() -> None:
    """Valider une facture déjà validée est refusé (409, inaltérabilité)."""
    session = _FakeSession([_facture("Validée", id_client=7)])
    response = await _valider(_app(session))

    assert response.status_code == 409
    assert "Validée" in response.json()["detail"]


async def test_valider_brouillon_sans_client_409() -> None:
    """Un brouillon sans client destinataire ne peut pas être validé (409)."""
    session = _FakeSession([_facture("Brouillon", id_client=None)])
    response = await _valider(_app(session))

    assert response.status_code == 409
    assert "client" in response.json()["detail"].lower()


async def test_valider_facture_hors_perimetre_404() -> None:
    """Facture inexistante ou d'une autre entreprise : 404 indistinct."""
    session = _FakeSession([None])
    response = await _valider(_app(session))

    assert response.status_code == 404
    assert "id_entreprise" in str(session.statements[0])


async def test_avoir_sur_facture_non_validee_409() -> None:
    """Générer un avoir depuis un brouillon est refusé (409, comme les autres
    refus de transition d'état)."""
    session = _FakeSession([_facture("Brouillon", id_client=7)])
    app = _app(session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/factures/42/avoir")

    assert response.status_code == 409
    assert "Validée" in response.json()["detail"]
