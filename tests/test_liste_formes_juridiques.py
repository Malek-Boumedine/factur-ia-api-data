"""Tests de la route du référentiel des formes juridiques
(``GET /formes-juridiques/``).

Sans base de données ni réseau : app minimale avec le router formes
juridiques, dépendance d'auth surchargée, session factice qui restitue des
résultats prédéfinis et capture les requêtes pour vérifier structurellement
le tri par libellé et le filtre actif. Référentiel global : aucune route
n'exige le header ``x-entreprise-id``.
"""

from typing import Any

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from src.auth.dependencies import get_current_user
from src.core.database import get_session
from src.entreprises.models import RefFormeJuridique
from src.formes_juridiques.router import router as formes_juridiques_router
from src.utilisateurs.models import Utilisateur


class _Result:
    def __init__(self, value: Any) -> None:
        self._value = value

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


def _forme(
    id_forme: int, code: str, libelle: str, est_actif: bool = True
) -> RefFormeJuridique:
    return RefFormeJuridique(
        id=id_forme,
        code=code,
        libelle=libelle,
        mention_tva_defaut=None,
        est_actif=est_actif,
    )


def _app(session: _FakeSession, *, authenticated: bool = True) -> FastAPI:
    app = FastAPI()
    app.include_router(formes_juridiques_router)
    app.dependency_overrides[get_session] = lambda: session
    if authenticated:
        app.dependency_overrides[get_current_user] = lambda: Utilisateur(
            id=1,
            nom="Test",
            prenom="User",
            email="user@example.com",
            hash_mot_de_passe="x",  # pragma: allowlist secret
        )
    return app


async def _get(app: FastAPI, params: dict[str, Any] | None = None) -> Any:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get("/formes-juridiques/", params=params or {})


async def test_liste_id_code_libelle() -> None:
    """La liste expose id, code, libellé et statut actif — et rien d'autre
    (`mention_tva_defaut` reste hors contrat)."""
    session = _FakeSession(
        [
            [
                _forme(2, "MICRO", "Micro-entreprise"),
                _forme(4, "SARL", "Société à responsabilité limitée"),
            ]
        ]
    )
    response = await _get(_app(session))

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert body[0] == {
        "id": 2,
        "code": "MICRO",
        "libelle": "Micro-entreprise",
        "est_actif": True,
    }
    assert set(body[1].keys()) == {"id", "code", "libelle", "est_actif"}


async def test_acces_sans_header_tenant() -> None:
    """Référentiel global : la route répond sans header `x-entreprise-id`
    (utilisateur en onboarding, pas encore rattaché à une entreprise)."""
    session = _FakeSession([[]])
    response = await _get(_app(session))

    assert response.status_code == 200
    assert response.json() == []


async def test_tri_par_libelle() -> None:
    """Le tri alphabétique par libellé est appliqué en base (bon défaut pour
    un select)."""
    session = _FakeSession([[]])
    response = await _get(_app(session))

    assert response.status_code == 200
    assert "ORDER BY ref_forme_juridique.libelle" in str(session.statements[0])


async def test_filtre_est_actif() -> None:
    """?est_actif=true : le filtre est poussé dans la requête (le front ne
    propose que les formes actives dans ses selects). Le booléen est rendu
    en littéral SQL, pas en paramètre lié."""
    session = _FakeSession([[_forme(4, "SARL", "Société à responsabilité limitée")]])
    response = await _get(_app(session), {"est_actif": "true"})

    assert response.status_code == 200
    assert "WHERE ref_forme_juridique.est_actif = true" in str(session.statements[0])


async def test_filtre_est_actif_false() -> None:
    """?est_actif=false : le filtre inverse est appliqué (formes désactivées
    seulement)."""
    session = _FakeSession([[_forme(9, "OLD", "Forme désactivée", est_actif=False)]])
    response = await _get(_app(session), {"est_actif": "false"})

    assert response.status_code == 200
    assert "WHERE ref_forme_juridique.est_actif = false" in str(session.statements[0])


async def test_sans_filtre_toutes_les_formes() -> None:
    """Sans paramètre, aucun filtre sur `est_actif` : les formes inactives
    sont incluses (affichage du libellé courant d'une entreprise existante)."""
    session = _FakeSession([[_forme(9, "OLD", "Forme désactivée", est_actif=False)]])
    response = await _get(_app(session))

    assert response.status_code == 200
    assert "WHERE" not in str(session.statements[0]).upper()
    assert response.json()[0]["est_actif"] is False


async def test_filtre_est_actif_invalide_422() -> None:
    """Valeur non booléenne : rejetée avant toute requête."""
    session = _FakeSession([])
    response = await _get(_app(session), {"est_actif": "peut-etre"})

    assert response.status_code == 422
    assert session.statements == []


async def test_non_authentifie_401() -> None:
    """Sans token, la route est inaccessible (401)."""
    session = _FakeSession([])
    response = await _get(_app(session, authenticated=False))

    assert response.status_code == 401
    assert session.statements == []
