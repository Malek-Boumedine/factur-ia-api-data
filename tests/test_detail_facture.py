"""Tests de la route de détail d'une facture (``GET /factures/{facture_id}``).

Sans base de données ni réseau : app minimale avec le router factures,
dépendances d'auth et de tenant surchargées, session factice qui restitue des
résultats prédéfinis et capture les requêtes émises (pour vérifier
structurellement l'isolation tenant et le chargement eager des lignes et
du statut).
"""

from decimal import Decimal
from typing import Any

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from src.auth.dependencies import get_current_user, verify_tenant_access
from src.core.database import get_session
from src.documents.models import ExtractionOcr
from src.factures.models import Facture, FactureLigne, StatutFacture
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


def _facture_avec_lignes() -> Facture:
    facture = Facture(
        id=42,
        id_entreprise=1,
        id_createur=1,
        numero_facture="BROUILLON-42",
        id_statut=1,
        total_ht=Decimal("100.00"),
        total_tva=Decimal("20.00"),
        total_ttc=Decimal("120.00"),
    )
    facture.statut_ref = StatutFacture(id=1, libelle="brouillon")
    facture.lignes = [
        FactureLigne(
            id=1,
            id_facture=42,
            ordre=1,
            designation="Prestation de conseil",
            quantite=Decimal("2.000"),
            unite="heure",
            prix_unitaire_ht=Decimal("40.00"),
            id_taux_tva=1,
            montant_ht=Decimal("80.00"),
            montant_tva=Decimal("16.00"),
            montant_ttc=Decimal("96.00"),
        ),
        FactureLigne(
            id=2,
            id_facture=42,
            ordre=2,
            designation="Frais de déplacement",
            quantite=Decimal("1.000"),
            unite=None,
            prix_unitaire_ht=Decimal("20.00"),
            id_taux_tva=1,
            montant_ht=Decimal("20.00"),
            montant_tva=Decimal("4.00"),
            montant_ttc=Decimal("24.00"),
        ),
    ]
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


async def _get(app: FastAPI, facture_id: int = 42) -> Any:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(f"/factures/{facture_id}")


async def test_facture_avec_lignes() -> None:
    """Facture trouvée : détail complet avec ses lignes et leurs montants.
    Sans extraction OCR liée, `extraction` est null. Le libellé du statut est
    résolu depuis le référentiel chargé en eager (mêmes valeurs que la liste)."""
    session = _FakeSession([_facture_avec_lignes(), None])
    response = await _get(_app(session))

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == 42
    assert body["numero_facture"] == "BROUILLON-42"
    assert body["total_ttc"] == "120.00"
    assert body["extraction"] is None
    assert body["libelle_statut"] == "brouillon"

    assert len(body["lignes"]) == 2
    ligne_1, ligne_2 = body["lignes"]
    assert ligne_1["designation"] == "Prestation de conseil"
    assert ligne_1["ordre"] == 1
    assert ligne_1["montant_ttc"] == "96.00"
    assert ligne_2["designation"] == "Frais de déplacement"
    assert ligne_2["ordre"] == 2

    # Isolation tenant dans la requête, et chargement eager des lignes
    # (une option de chargement est bien attachée au select).
    statement = session.statements[0]
    assert "id_entreprise" in str(statement)
    assert statement._with_options


async def test_facture_ocr_expose_extraction() -> None:
    """Facture issue d'un OCR : `extraction` expose le score global, le type
    de document détecté et les scores par champ, reparsés en Decimal depuis
    les chaînes stockées (sérialisés en chaînes dans le JSON de réponse)."""
    extraction = ExtractionOcr(
        id=9,
        id_document=3,
        id_facture=42,
        score_confiance=Decimal("0.95"),
        type_document="facture",
        par_champ={"total_ht": "0.9876", "iban": "0.5000"},
    )
    session = _FakeSession([_facture_avec_lignes(), extraction])
    response = await _get(_app(session))

    assert response.status_code == 200
    body = response.json()
    assert body["extraction"] == {
        "score_confiance": "0.95",
        "type_document": "facture",
        "par_champ": {"total_ht": "0.9876", "iban": "0.5000"},
    }

    # La résolution vise bien l'extraction liée à la facture
    statement_extraction = session.statements[1]
    assert "extraction_ocr" in str(statement_extraction)
    assert "id_facture" in str(statement_extraction)


async def test_statut_orphelin_libelle_statut_null() -> None:
    """Référentiel incohérent (statut non résolu) : `libelle_statut` est null,
    le détail répond 200 plutôt qu'un 500."""
    facture = _facture_avec_lignes()
    facture.statut_ref = None
    session = _FakeSession([facture, None])
    response = await _get(_app(session))

    assert response.status_code == 200
    assert response.json()["libelle_statut"] is None


async def test_facture_hors_perimetre_ou_inexistante_404() -> None:
    """Facture inexistante ou d'une autre entreprise : même 404 indistinct."""
    session = _FakeSession([None])
    response = await _get(_app(session))

    assert response.status_code == 404
    assert response.json()["detail"] == "Facture introuvable dans cet espace entreprise"


async def test_non_authentifie_401() -> None:
    """Sans token, la route est inaccessible (401)."""
    session = _FakeSession([])
    app = _app(session, authenticated=False)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/factures/42", headers={"X-Entreprise-Id": "1"})

    assert response.status_code == 401
    assert session.statements == []
