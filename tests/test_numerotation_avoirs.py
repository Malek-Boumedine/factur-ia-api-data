"""Tests de la numérotation distincte des avoirs à la validation.

Sans base de données ni réseau : mêmes doublures que les autres tests factures.
Un avoir validé reçoit un numéro ``AV-YYYYMM-XXXX``, une facture garde
``FAC-YYYYMM-XXXX``. Les deux séries sont indépendantes et chacune reste
continue (séries distinctes, BOI-TVA-DECLA-30-20-20-10) : la séquence d'une
série s'incrémente depuis son propre dernier numéro et ignore l'autre série.
"""

import re
from datetime import datetime
from decimal import Decimal
from typing import Any

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from src.auth.dependencies import get_current_user, verify_tenant_access
from src.core.database import get_session
from src.factures.models import Facture, StatutFacture, TypeFacture
from src.factures.router import router as factures_router
from src.utilisateurs.models import Utilisateur


class _Result:
    def __init__(self, value: Any) -> None:
        self._value = value

    def first(self) -> Any:
        return self._value


class _FakeSession:
    """Session factice : dépile des résultats prévus et trace les requêtes."""

    def __init__(
        self, results: list[Any], gets: dict[tuple[Any, Any], Any] | None = None
    ) -> None:
        self._results = results
        self._gets = gets or {}
        self.statements: list[Any] = []

    async def exec(self, statement: Any) -> _Result:
        self.statements.append(statement)
        return _Result(self._results.pop(0))

    async def get(self, model: Any, key: Any) -> Any:
        return self._gets.get((model, key))

    async def commit(self) -> None:
        pass


def _brouillon(type_facture: TypeFacture) -> Facture:
    facture = Facture(
        id=42,
        id_entreprise=1,
        id_createur=1,
        id_client=7,
        numero_facture="BROUILLON-42",
        type_facture=type_facture,
        id_statut=1,
        total_ht=Decimal("100.00"),
        total_tva=Decimal("20.00"),
        total_ttc=Decimal("120.00"),
    )
    if type_facture == TypeFacture.AVOIR:
        facture.id_facture_origine = 41
    facture.statut_ref = StatutFacture(id=1, libelle="Brouillon")
    facture.lignes = []
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


def _session_validation(facture: Facture, dernier_numero: str | None) -> _FakeSession:
    # Ordre des exec : facture, statut "Validée", dernier numéro de la
    # série du mois, rechargement final
    return _FakeSession(
        [facture, StatutFacture(id=2, libelle="Validée"), dernier_numero, facture]
    )


async def _valider(app: FastAPI) -> Any:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post("/factures/42/valider")


def _clause_sequence(session: _FakeSession) -> str:
    """Rend la requête du dernier numéro avec ses valeurs littérales."""
    return str(session.statements[2].compile(compile_kwargs={"literal_binds": True}))


async def test_avoir_valide_recoit_numero_av() -> None:
    """Premier avoir du mois : numéro AV-YYYYMM-0001, série vide au départ."""
    session = _session_validation(_brouillon(TypeFacture.AVOIR), None)
    response = await _valider(_app(session))

    assert response.status_code == 200
    assert re.fullmatch(r"AV-\d{6}-0001", response.json()["numero_facture"])


async def test_facture_validee_garde_le_format_fac() -> None:
    """Une facture classique continue sa série FAC- sans trou."""
    mois = datetime.now().strftime("%Y%m")
    session = _session_validation(_brouillon(TypeFacture.FACTURE), f"FAC-{mois}-0007")
    response = await _valider(_app(session))

    assert response.status_code == 200
    assert response.json()["numero_facture"] == f"FAC-{mois}-0008"


async def test_sequence_avoir_continue_sans_trou() -> None:
    """La série AV- s'incrémente depuis son propre dernier numéro."""
    mois = datetime.now().strftime("%Y%m")
    session = _session_validation(_brouillon(TypeFacture.AVOIR), f"AV-{mois}-0004")
    response = await _valider(_app(session))

    assert response.status_code == 200
    assert response.json()["numero_facture"] == f"AV-{mois}-0005"


async def test_serie_avoir_ignore_les_numeros_fac() -> None:
    """La recherche du dernier numéro d'un avoir filtre sur le préfixe AV- :
    les FAC- existants ne sont ni comptés ni écrasés (pas de collision)."""
    mois = datetime.now().strftime("%Y%m")
    session = _session_validation(_brouillon(TypeFacture.AVOIR), None)
    response = await _valider(_app(session))

    assert response.status_code == 200
    clause = _clause_sequence(session)
    assert f"AV-{mois}-" in clause
    assert "FAC-" not in clause


async def test_serie_facture_ignore_les_numeros_av() -> None:
    """Symétrique : la séquence d'une facture ne regarde que la série FAC-."""
    mois = datetime.now().strftime("%Y%m")
    session = _session_validation(_brouillon(TypeFacture.FACTURE), None)
    response = await _valider(_app(session))

    assert response.status_code == 200
    assert f"FAC-{mois}-" in _clause_sequence(session)
