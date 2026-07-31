"""Tests de la règle de génération d'avoir (``POST /factures/{id}/avoir``).

Sans base de données ni réseau : mêmes doublures que les autres tests
factures. La règle métier raisonne par famille de statuts : toute facture
émise (famille non-brouillon — validée, payée, en retard, statuts PDP…)
peut faire l'objet d'un avoir, seul moyen légal de corriger une facture
inaltérable. Refus (409) : brouillon (à valider d'abord), facture annulée
(déjà annulée par un avoir) et avoir (pas d'avoir d'avoir). Vérifie aussi
l'inversion comptable (totaux et lignes en négatif, lien vers l'origine).
"""

from decimal import Decimal
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from src.auth.dependencies import get_current_user, verify_tenant_access
from src.core.database import get_session
from src.factures.models import Facture, FactureLigne, StatutFacture, TypeFacture
from src.factures.router import router as factures_router
from src.utilisateurs.models import Utilisateur


class _Result:
    def __init__(self, value: Any) -> None:
        self._value = value

    def first(self) -> Any:
        return self._value


class _FakeSession:
    """Session factice : dépile des résultats prévus et trace les requêtes.

    Un résultat callable est évalué avec la session au moment du ``exec``,
    ce qui permet de renvoyer un objet ajouté plus tôt via ``add``.
    """

    def __init__(self, results: list[Any]) -> None:
        self._results = results
        self.statements: list[Any] = []
        self.added: list[Any] = []

    async def exec(self, statement: Any) -> _Result:
        self.statements.append(statement)
        value = self._results.pop(0)
        if callable(value):
            value = value(self)
        return _Result(value)

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        # Simule l'attribution d'une clé primaire par la base
        for index, obj in enumerate(self.added):
            if getattr(obj, "id", None) is None:
                obj.id = 100 + index

    async def commit(self) -> None:
        pass


def _facture_origine(
    statut: str, type_facture: TypeFacture = TypeFacture.FACTURE
) -> Facture:
    facture = Facture(
        id=42,
        id_entreprise=1,
        id_createur=1,
        id_client=7,
        numero_facture="FAC-202607-0001",
        type_facture=type_facture,
        id_statut=2,
        total_ht=Decimal("100.00"),
        total_tva=Decimal("20.00"),
        total_ttc=Decimal("120.00"),
    )
    facture.statut_ref = StatutFacture(id=2, libelle=statut)
    facture.lignes = [
        FactureLigne(
            id=1,
            id_facture=42,
            ordre=0,
            designation="Prestation",
            quantite=Decimal("2.00"),
            unite="jour",
            prix_unitaire_ht=Decimal("50.00"),
            id_taux_tva=1,
            montant_ht=Decimal("100.00"),
            montant_tva=Decimal("20.00"),
            montant_ttc=Decimal("120.00"),
        )
    ]
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


async def _generer_avoir(session: _FakeSession) -> Any:
    transport = ASGITransport(app=_app(session))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post("/factures/42/avoir")


def _session_succes(origine: Facture) -> _FakeSession:
    # Ordre des exec : facture d'origine, statut "Brouillon" pour l'avoir,
    # rechargement final (l'avoir ajouté à la session)
    return _FakeSession(
        [origine, StatutFacture(id=1, libelle="Brouillon"), lambda s: s.added[0]]
    )


@pytest.mark.parametrize(
    "statut",
    [
        "validée",
        "Validée",
        "payee",
        "partiellement_payee",
        "en_retard",
        "envoyee_client",
        "en_attente_pdp",
        "deposee_pdp",
        "rejetee_pdp",
        "erreur_transmission",
        "contestee",
    ],
)
async def test_avoir_possible_sur_toute_facture_emise(statut: str) -> None:
    """Une facture qui progresse dans son cycle de vie (payée, déposée PDP,
    en retard, rejetée PDP…) reste une facture émise : l'avoir doit rester
    possible, y compris avec un libellé capitalisé en base."""
    response = await _generer_avoir(_session_succes(_facture_origine(statut)))

    assert response.status_code == 201
    body = response.json()
    assert body["type_facture"] == "avoir"
    assert body["id_facture_origine"] == 42
    # Portée du champ : résolu sur la route de détail uniquement,
    # null sur les réponses de création/modification.
    assert body["libelle_statut"] is None


@pytest.mark.parametrize("statut", ["brouillon", "Brouillon"])
async def test_avoir_refuse_sur_brouillon(statut: str) -> None:
    """Un brouillon n'est pas émis : rien à corriger par avoir (409)."""
    response = await _generer_avoir(_FakeSession([_facture_origine(statut)]))

    assert response.status_code == 409
    assert "Validez d'abord" in response.json()["detail"]


async def test_avoir_refuse_sur_facture_annulee() -> None:
    """Une facture annulée est déjà soldée par un avoir : un second
    créerait un double crédit comptable (409)."""
    response = await _generer_avoir(_FakeSession([_facture_origine("annulee")]))

    assert response.status_code == 409
    assert "déjà annulée" in response.json()["detail"]


async def test_avoir_refuse_sur_un_avoir() -> None:
    """Pas d'avoir d'avoir : re-négativer les montants n'a pas de sens
    comptable ; un avoir erroné se corrige par une nouvelle facture (409)."""
    origine = _facture_origine("validée", type_facture=TypeFacture.AVOIR)
    response = await _generer_avoir(_FakeSession([origine]))

    assert response.status_code == 409
    assert "à partir d'un avoir" in response.json()["detail"]


async def test_avoir_inverse_montants_et_lignes() -> None:
    """L'avoir recopie l'origine en négatif : totaux, quantités et montants
    de lignes inversés, lien comptable vers la facture d'origine."""
    session = _session_succes(_facture_origine("deposee_pdp"))
    response = await _generer_avoir(session)

    assert response.status_code == 201
    avoir = session.added[0]
    assert avoir.total_ht == Decimal("-100.00")
    assert avoir.total_tva == Decimal("-20.00")
    assert avoir.total_ttc == Decimal("-120.00")
    assert avoir.id_facture_origine == 42

    lignes = [obj for obj in session.added if isinstance(obj, FactureLigne)]
    assert len(lignes) == 1
    assert lignes[0].quantite == Decimal("-2.00")
    assert lignes[0].montant_ttc == Decimal("-120.00")
