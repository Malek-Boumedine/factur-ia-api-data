"""Tests de la route de liste des factures (``GET /factures/``).

Sans base de données ni réseau : app minimale avec le router factures,
dépendances d'auth et de tenant surchargées, session factice qui restitue
des résultats prédéfinis (comptage puis page) et capture les requêtes pour
vérifier structurellement les filtres, la recherche, le tri, la pagination
et l'isolation tenant.
"""

from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from src.auth.dependencies import get_current_user, verify_tenant_access
from src.clients.models import Client
from src.core.database import get_session
from src.factures.models import Facture, TypeFacture
from src.factures.router import router as factures_router
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


def _brouillon() -> Facture:
    """Brouillon sans snapshot : le nom vient du client lié (jointure)."""
    facture = Facture(
        id=1,
        id_entreprise=1,
        id_createur=1,
        id_client=7,
        numero_facture="BROUILLON-A1B2C3",
        date_emission=date(2026, 7, 20),
        type_facture=TypeFacture.FACTURE,
        id_statut=1,
        total_ht=Decimal("100.00"),
        total_tva=Decimal("20.00"),
        total_ttc=Decimal("120.00"),
    )
    facture.client = Client(id=7, raison_sociale="Client Courant SARL")
    return facture


def _validee() -> Facture:
    """Facture validée : le nom vient du snapshot figé, prioritaire sur le
    client lié (dont la raison sociale a pu changer depuis)."""
    facture = Facture(
        id=2,
        id_entreprise=1,
        id_createur=1,
        id_client=8,
        numero_facture="FAC-202607-0001",
        date_emission=date(2026, 7, 10),
        type_facture=TypeFacture.FACTURE,
        id_statut=2,
        snapshot_client={"raison_sociale": "Snapshot Historique SA"},
        total_ht=Decimal("500.00"),
        total_tva=Decimal("100.00"),
        total_ttc=Decimal("600.00"),
    )
    facture.client = Client(id=8, raison_sociale="Nom Actuel Différent SA")
    return facture


def _app(session: _FakeSession, *, authenticated: bool = True) -> FastAPI:
    app = FastAPI()
    app.include_router(factures_router)
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
        return await client.get("/factures/", params=params or {})


def _bound_params(statement: Any) -> list[Any]:
    return list(statement.compile().params.values())


async def test_liste_mixte_nom_destinataire_resolu() -> None:
    """Brouillon et validée ensemble : chacun ressort avec son nom résolu
    (client lié pour le brouillon, snapshot prioritaire pour la validée)."""
    session = _FakeSession([2, [_brouillon(), _validee()]])
    response = await _get(_app(session))

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert body["skip"] == 0
    assert body["limit"] == 100
    assert len(body["items"]) == 2

    brouillon, validee = body["items"]
    assert brouillon["numero_facture"] == "BROUILLON-A1B2C3"
    assert brouillon["nom_destinataire"] == "Client Courant SARL"
    # Le snapshot figé prime sur la raison sociale actuelle du client
    assert validee["numero_facture"] == "FAC-202607-0001"
    assert validee["nom_destinataire"] == "Snapshot Historique SA"

    # Les lignes ne sont pas exposées dans le listing (schéma allégé)
    assert "lignes" not in brouillon

    # Isolation tenant dans le comptage et dans la page
    assert "id_entreprise" in str(session.statements[0])
    assert "id_entreprise" in str(session.statements[1])


async def test_facture_sans_client_nom_destinataire_null() -> None:
    """Brouillon sans client rattaché : nom_destinataire est null, pas d'erreur."""
    facture = _brouillon()
    facture.id_client = None
    facture.client = None
    session = _FakeSession([1, [facture]])
    response = await _get(_app(session))

    assert response.status_code == 200
    assert response.json()["items"][0]["nom_destinataire"] is None


async def test_filtre_statut_brouillon() -> None:
    """?statut=Brouillon : jointure sur le référentiel des statuts et filtre
    sur le libellé (onglet « Brouillons » du front)."""
    session = _FakeSession([1, [_brouillon()]])
    response = await _get(_app(session), {"statut": "Brouillon"})

    assert response.status_code == 200
    page_statement = session.statements[1]
    assert "JOIN statut_facture" in str(page_statement)
    assert "statut_facture.libelle" in str(page_statement)
    assert "Brouillon" in _bound_params(page_statement)
    # Le comptage applique le même filtre (total cohérent avec l'onglet)
    assert "Brouillon" in _bound_params(session.statements[0])


async def test_filtre_statut_validee() -> None:
    """?statut=Validée : même mécanique pour l'onglet « Factures validées »."""
    session = _FakeSession([1, [_validee()]])
    response = await _get(_app(session), {"statut": "Validée"})

    assert response.status_code == 200
    page_statement = session.statements[1]
    assert "JOIN statut_facture" in str(page_statement)
    assert "Validée" in _bound_params(page_statement)
    assert "Validée" in _bound_params(session.statements[0])


async def test_pagination_dans_statut_filtre() -> None:
    """Pagination à l'intérieur d'un statut filtré : le filtre reste appliqué
    au comptage ET à la tranche, l'enveloppe reflète skip/limit/total."""
    session = _FakeSession([12, [_validee()]])
    response = await _get(_app(session), {"statut": "Validée", "skip": 10, "limit": 2})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 12
    assert body["skip"] == 10
    assert body["limit"] == 2

    # La tranche est bien découpée sur la requête filtrée par statut
    page_params = _bound_params(session.statements[1])
    assert "Validée" in page_params
    assert 10 in page_params
    assert 2 in page_params
    # Le comptage porte sur la même requête filtrée (pas de LIMIT dedans)
    assert "Validée" in _bound_params(session.statements[0])


async def test_filtre_dates_inclusives() -> None:
    """Bornes min/max incluses sur date_emission."""
    session = _FakeSession([0, []])
    response = await _get(
        _app(session),
        {"date_emission_min": "2026-07-01", "date_emission_max": "2026-07-31"},
    )

    assert response.status_code == 200
    page_statement = str(session.statements[1])
    assert "date_emission >=" in page_statement
    assert "date_emission <=" in page_statement
    params = _bound_params(session.statements[1])
    assert date(2026, 7, 1) in params
    assert date(2026, 7, 31) in params


async def test_filtres_type_et_client() -> None:
    """Filtres type_facture et id_client appliqués dans la requête."""
    session = _FakeSession([0, []])
    response = await _get(_app(session), {"type_facture": "avoir", "id_client": 7})

    assert response.status_code == 200
    page_statement = str(session.statements[1])
    assert "type_facture" in page_statement
    params = _bound_params(session.statements[1])
    assert TypeFacture.AVOIR in params
    assert 7 in params


async def test_recherche_multi_colonnes() -> None:
    """La recherche couvre numéro, référence de commande et raison sociale du
    client (left join : les factures sans client restent listées)."""
    session = _FakeSession([0, []])
    response = await _get(_app(session), {"search": "dupont"})

    assert response.status_code == 200
    page_statement = str(session.statements[1])
    assert "LEFT OUTER JOIN client" in page_statement
    assert "numero_facture" in page_statement
    assert "reference_commande" in page_statement
    assert "raison_sociale" in page_statement
    assert "%dupont%" in _bound_params(session.statements[1])


async def test_tri_plus_recentes_d_abord() -> None:
    """Tri par date d'émission décroissante, id décroissant en départage."""
    session = _FakeSession([0, []])
    response = await _get(_app(session))

    assert response.status_code == 200
    assert "ORDER BY facture.date_emission DESC, facture.id DESC" in str(
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
        response = await client.get("/factures/", headers={"X-Entreprise-Id": "1"})

    assert response.status_code == 401
    assert session.statements == []
