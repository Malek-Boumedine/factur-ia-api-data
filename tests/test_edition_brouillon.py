"""Tests de la route d'édition d'un brouillon (``PATCH /factures/{facture_id}``).

Sans base de données ni réseau : app minimale avec le router factures,
dépendances d'auth et de tenant surchargées, session factice qui restitue des
résultats prédéfinis et capture les objets ajoutés/supprimés (pour vérifier
le remplacement des lignes et le recalcul des totaux).
"""

from decimal import Decimal
from typing import Any

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from src.auth.dependencies import get_current_user, verify_tenant_access
from src.core.database import get_session
from src.factures.models import (
    Facture,
    FactureLigne,
    StatutFacture,
    TauxTva,
    TypeFacture,
)
from src.factures.router import router as factures_router
from src.utilisateurs.models import Utilisateur


class _Result:
    def __init__(self, value: Any) -> None:
        self._value = value

    def first(self) -> Any:
        return self._value

    def all(self) -> Any:
        return self._value


class _FakeSession:
    """Session factice : dépile des résultats prévus et trace les opérations."""

    def __init__(self, results: list[Any]) -> None:
        self._results = results
        self.statements: list[Any] = []
        self.added: list[Any] = []
        self.deleted: list[Any] = []

    async def exec(self, statement: Any) -> _Result:
        self.statements.append(statement)
        return _Result(self._results.pop(0))

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def delete(self, obj: Any) -> None:
        self.deleted.append(obj)

    async def flush(self) -> None:
        pass

    async def commit(self) -> None:
        pass


def _facture_brouillon(**overrides: Any) -> Facture:
    facture = Facture(
        id=42,
        id_entreprise=1,
        id_createur=1,
        id_client=7,
        numero_facture="BROUILLON-42",
        id_statut=1,
        total_ht=Decimal("100.00"),
        total_tva=Decimal("20.00"),
        total_ttc=Decimal("120.00"),
        **overrides,
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


def _taux_20() -> TauxTva:
    return TauxTva(id=1, taux=Decimal("20.00"), libelle="TVA Normale 20%")


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


async def _patch(app: FastAPI, payload: dict[str, Any], facture_id: int = 42) -> Any:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.patch(f"/factures/{facture_id}", json=payload)


async def test_edition_en_tete_seule() -> None:
    """Sans lignes dans le payload : l'en-tête change, lignes et totaux intacts."""
    facture = _facture_brouillon()
    session = _FakeSession([facture, facture])
    response = await _patch(
        _app(session),
        {"notes": "Corrigé après relecture", "date_echeance": "2026-08-31"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["notes"] == "Corrigé après relecture"
    assert body["date_echeance"] == "2026-08-31"
    # Champs non envoyés inchangés, aucune ligne supprimée, totaux intacts
    assert body["id_client"] == 7
    assert body["total_ttc"] == "120.00"
    assert session.deleted == []
    assert session.added == []

    # Isolation tenant dans la requête de chargement
    assert "id_entreprise" in str(session.statements[0])


async def test_remplacement_lignes_et_recalcul_totaux() -> None:
    """Payload avec lignes : anciennes supprimées,
    nouvelles créées, totaux recalculés.
    """
    facture = _facture_brouillon()
    session = _FakeSession([facture, [_taux_20()], facture])
    response = await _patch(
        _app(session),
        {
            "lignes": [
                {
                    "designation": "Nouvelle prestation",
                    "quantite": "3.000",
                    "prix_unitaire_ht": "10.00",
                    "id_taux_tva": 1,
                }
            ]
        },
    )

    assert response.status_code == 200
    body = response.json()
    # Totaux recalculés depuis la nouvelle liste (3 x 10.00 HT, TVA 20 %)
    assert body["total_ht"] == "30.00"
    assert body["total_tva"] == "6.00"
    assert body["total_ttc"] == "36.00"

    # Les 2 anciennes lignes ont été supprimées
    assert len(session.deleted) == 2

    # Une seule nouvelle ligne créée, montants calculés par le service
    assert len(session.added) == 1
    nouvelle_ligne = session.added[0]
    assert nouvelle_ligne.designation == "Nouvelle prestation"
    assert nouvelle_ligne.ordre == 0
    assert nouvelle_ligne.montant_ht == Decimal("30.00")
    assert nouvelle_ligne.montant_tva == Decimal("6.00")
    assert nouvelle_ligne.montant_ttc == Decimal("36.00")


async def test_edition_siret_emetteur_et_destinataire() -> None:
    """Les deux SIRET sont éditables sur un brouillon : espaces OCR retirés,
    SIRET incomplet accepté (état de travail)."""
    facture = _facture_brouillon(siret_emetteur="11111111111111")
    session = _FakeSession([facture, facture])
    response = await _patch(
        _app(session),
        {
            "siret_emetteur": "222 222 222 22222",  # 14 chiffres avec espaces OCR
            "siret_destinataire": "404833048",  # SIREN incomplet toléré
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["siret_emetteur"] == "22222222222222"
    assert body["siret_destinataire"] == "404833048"


async def test_effacement_siret_via_null_et_vide() -> None:
    """``null`` explicite ou chaîne vide/espaces efface un SIRET du brouillon."""
    facture = _facture_brouillon(
        siret_emetteur="11111111111111", siret_destinataire="22222222222222"
    )
    session = _FakeSession([facture, facture])
    response = await _patch(
        _app(session),
        {"siret_emetteur": None, "siret_destinataire": "   "},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["siret_emetteur"] is None
    assert body["siret_destinataire"] is None


async def test_siret_aberrant_422() -> None:
    """Caractères non numériques ou longueur > 14 : rejet en 422 par champ."""
    session = _FakeSession([])
    response = await _patch(
        _app(session),
        {
            # lettre au milieu
            "siret_emetteur": "12A45678900012",  # pragma: allowlist secret
            "siret_destinataire": "123456789000123",  # 15 chiffres
        },
    )

    assert response.status_code == 422
    locs = [tuple(err["loc"]) for err in response.json()["detail"]]
    assert ("body", "siret_emetteur") in locs
    assert ("body", "siret_destinataire") in locs
    # Aucune requête émise : rejeté avant d'atteindre la base
    assert session.statements == []


async def test_edition_siret_sur_facture_validee_409() -> None:
    """Les SIRET d'une facture validée sont figés : édition refusée (409)."""
    facture = _facture_brouillon()
    facture.statut_ref = StatutFacture(id=2, libelle="Validée")
    session = _FakeSession([facture])
    response = await _patch(_app(session), {"siret_destinataire": "22222222222222"})

    assert response.status_code == 409


async def test_facture_validee_immuable_409() -> None:
    """Une facture validée est immuable : toute édition est refusée (409)."""
    facture = _facture_brouillon()
    facture.statut_ref = StatutFacture(id=2, libelle="Validée")
    session = _FakeSession([facture])
    response = await _patch(_app(session), {"notes": "tentative"})

    assert response.status_code == 409
    assert "Validée" in response.json()["detail"]
    # Rien n'a été modifié ni supprimé
    assert session.deleted == []
    assert session.added == []


async def test_type_facture_avoir_lie_409() -> None:
    """Un avoir lié à une facture d'origine ne peut pas changer de type."""
    facture = _facture_brouillon(type_facture=TypeFacture.AVOIR, id_facture_origine=10)
    session = _FakeSession([facture])
    response = await _patch(_app(session), {"type_facture": "facture"})

    assert response.status_code == 409
    assert "avoir" in response.json()["detail"].lower()


async def test_facture_hors_perimetre_ou_inexistante_404() -> None:
    """Facture inexistante ou d'une autre entreprise : même 404 indistinct."""
    session = _FakeSession([None])
    response = await _patch(_app(session), {"notes": "x"})

    assert response.status_code == 404
    assert response.json()["detail"] == "Facture introuvable dans cet espace entreprise"
    assert "id_entreprise" in str(session.statements[0])


async def test_taux_tva_inconnu_400() -> None:
    """Un id_taux_tva inexistant en base est signalé en 400 (comme au POST)."""
    facture = _facture_brouillon()
    # La requête des taux ne trouve rien
    session = _FakeSession([facture, []])
    response = await _patch(
        _app(session),
        {
            "lignes": [
                {
                    "designation": "Presta",
                    "quantite": "1.000",
                    "prix_unitaire_ht": "10.00",
                    "id_taux_tva": 999,
                }
            ]
        },
    )

    assert response.status_code == 400
    assert "999" in response.json()["detail"]


async def test_payload_invalide_422_par_champ() -> None:
    """Les erreurs de validation pointent le champ fautif (mapping formulaire)."""
    session = _FakeSession([])
    response = await _patch(
        _app(session),
        {
            "devise": None,  # null explicite refusé (champ non nullable)
            "lignes": [
                {
                    "designation": "Presta",
                    "quantite": "abc",  # pas un nombre
                    "prix_unitaire_ht": "10.00",
                    "id_taux_tva": 1,
                }
            ],
        },
    )

    assert response.status_code == 422
    locs = [tuple(err["loc"]) for err in response.json()["detail"]]
    assert ("body", "devise") in locs
    assert ("body", "lignes", 0, "quantite") in locs
    # Aucune requête émise : rejeté avant d'atteindre la base
    assert session.statements == []


async def test_lignes_vides_422() -> None:
    """Remplacer les lignes par une liste vide est refusé (au moins 1 ligne)."""
    session = _FakeSession([])
    response = await _patch(_app(session), {"lignes": []})

    assert response.status_code == 422
    locs = [tuple(err["loc"]) for err in response.json()["detail"]]
    assert ("body", "lignes") in locs


async def test_non_authentifie_401() -> None:
    """Sans token, la route est inaccessible (401)."""
    session = _FakeSession([])
    app = _app(session, authenticated=False)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.patch(
            "/factures/42", json={"notes": "x"}, headers={"X-Entreprise-Id": "1"}
        )

    assert response.status_code == 401
    assert session.statements == []
