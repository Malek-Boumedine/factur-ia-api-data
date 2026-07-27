"""Tests de la route de suppression d'un brouillon (``DELETE /factures/{facture_id}``).

Sans base de données ni réseau : app minimale avec le router factures,
dépendances d'auth et de tenant surchargées, session factice qui restitue des
résultats prédéfinis et trace les opérations dans l'ordre (pour vérifier que
le détachement des extractions OCR et les suppressions de lignes précèdent
bien le DELETE de la facture, et que rien d'autre n'est touché).
"""

from decimal import Decimal
from typing import Any

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from src.auth.dependencies import get_current_user, verify_tenant_access
from src.core.database import get_session
from src.factures.models import Facture, FactureLigne, StatutFacture
from src.factures.router import router as factures_router
from src.utilisateurs.models import Utilisateur


class _Result:
    def __init__(self, value: Any) -> None:
        self._value = value

    def first(self) -> Any:
        return self._value


class _FakeSession:
    """Session factice : dépile des résultats prévus et trace chaque opération
    dans l'ordre d'émission (``operations``) pour vérifier le séquencement."""

    def __init__(self, results: list[Any]) -> None:
        self._results = results
        self.statements: list[Any] = []
        self.executed: list[Any] = []
        self.deleted: list[Any] = []
        self.committed = False
        self.operations: list[tuple[str, Any]] = []

    async def exec(self, statement: Any) -> _Result:
        self.statements.append(statement)
        return _Result(self._results.pop(0))

    async def execute(self, statement: Any) -> None:
        self.executed.append(statement)
        self.operations.append(("execute", statement))

    async def delete(self, obj: Any) -> None:
        self.deleted.append(obj)
        self.operations.append(("delete", obj))

    async def flush(self) -> None:
        self.operations.append(("flush", None))

    async def commit(self) -> None:
        self.committed = True
        self.operations.append(("commit", None))


def _facture_brouillon() -> Facture:
    facture = Facture(
        id=42,
        id_entreprise=1,
        id_createur=1,
        id_client=7,
        id_document=3,
        numero_facture="BROUILLON-42",
        id_statut=1,
        total_ht=Decimal("100.00"),
        total_tva=Decimal("20.00"),
        total_ttc=Decimal("120.00"),
    )
    facture.statut_ref = StatutFacture(id=1, libelle="Brouillon")
    facture.lignes = [
        FactureLigne(
            id=1,
            id_facture=42,
            ordre=0,
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
            ordre=1,
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


async def _delete(app: FastAPI, facture_id: int = 42) -> Any:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.delete(f"/factures/{facture_id}")


async def test_suppression_brouillon_204() -> None:
    """Brouillon supprimé : 204 sans corps, opérations émises dans l'ordre
    détachement extraction → suppression lignes → flush → suppression facture
    → commit (l'UPDATE et les DELETE lignes doivent précéder le DELETE facture,
    sinon la FK extraction_ocr.id_facture bloque en base)."""
    facture = _facture_brouillon()
    session = _FakeSession([facture])
    response = await _delete(_app(session))

    assert response.status_code == 204
    assert response.content == b""

    # Séquencement exact des opérations
    kinds = [kind for kind, _ in session.operations]
    assert kinds == ["execute", "delete", "delete", "flush", "delete", "commit"]

    # 1. Détachement : UPDATE extraction_ocr SET id_facture = NULL pour cette
    # facture — l'extraction est conservée, seule la référence est effacée.
    detach_statement = session.executed[0]
    assert "UPDATE extraction_ocr" in str(detach_statement)
    assert "id_facture" in str(detach_statement)
    params = detach_statement.compile().params
    assert params["id_facture"] is None
    assert 42 in params.values()

    # 2. Puis les 2 lignes, puis la facture (pas de lignes orphelines) ;
    # rien d'autre n'est supprimé (le document source n'est pas touché).
    assert session.deleted[:2] == facture.lignes
    assert session.deleted[2] is facture
    assert session.committed

    # Isolation tenant dans la requête de chargement
    assert "id_entreprise" in str(session.statements[0])


async def test_facture_validee_non_supprimable_409() -> None:
    """Une facture validée est immuable : la suppression est refusée (409)."""
    facture = _facture_brouillon()
    facture.statut_ref = StatutFacture(id=2, libelle="Validée")
    session = _FakeSession([facture])
    response = await _delete(_app(session))

    assert response.status_code == 409
    assert "Validée" in response.json()["detail"]
    # Rien n'a été supprimé, détaché ni commité
    assert session.deleted == []
    assert session.executed == []
    assert not session.committed


async def test_facture_hors_perimetre_ou_inexistante_404() -> None:
    """Facture inexistante ou d'une autre entreprise : même 404 indistinct."""
    session = _FakeSession([None])
    response = await _delete(_app(session))

    assert response.status_code == 404
    assert response.json()["detail"] == "Facture introuvable dans cet espace entreprise"
    assert session.deleted == []


async def test_non_authentifie_401() -> None:
    """Sans token, la route est inaccessible (401)."""
    session = _FakeSession([])
    app = _app(session, authenticated=False)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.delete("/factures/42", headers={"X-Entreprise-Id": "1"})

    assert response.status_code == 401
    assert session.statements == []
    assert session.deleted == []
