"""Tests du rapport de conformité Factur-X (profil MINIMUM).

Sans base de données ni réseau : mêmes doublures que les tests de génération.
Couvre la route ``GET /factures/{id}/facturx/conformite`` (rapport structuré,
garde-fous 409 brouillon et 404 hors périmètre) et les règles métier de
``check_facturx_minimum`` : champs obligatoires, format et clé de Luhn des
SIRET (exemption La Poste, sévérité de la clé pilotée par
``SIRET_LUHN_STRICT``), cohérence et signe des totaux, collecte de tous
les problèmes sans arrêt au premier. Vérifie aussi que la génération partage
les mêmes règles (409 sur montants incohérents).
"""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from src.auth.dependencies import get_current_user, verify_tenant_access
from src.core.config import settings
from src.core.database import get_session
from src.entreprises.models import Entreprise
from src.factures.models import Facture, StatutFacture, TypeFacture
from src.factures.router import router as factures_router
from src.facturx.conformite import check_facturx_minimum
from src.utilisateurs.models import Utilisateur

# SIRET factices à clé de Luhn valide.
SIRET_EMETTEUR = "12345678900015"
SIRET_DESTINATAIRE = "98765432100023"
# SIRET La Poste : clé de Luhn invalide, mais exemption officielle (SIREN 356000000).
SIRET_LA_POSTE = "35600000000049"


class _Result:
    def __init__(self, value: Any) -> None:
        self._value = value

    def first(self) -> Any:
        return self._value


class _FakeSession:
    """Session factice : dépile des résultats prévus et sert les ``get``."""

    def __init__(
        self, results: list[Any], gets: dict[tuple[Any, Any], Any] | None = None
    ) -> None:
        self._results = results
        self._gets = gets or {}

    async def exec(self, statement: Any) -> _Result:
        return _Result(self._results.pop(0))

    async def get(self, model: Any, key: Any) -> Any:
        return self._gets.get((model, key))


def _entreprise() -> Entreprise:
    return Entreprise(id=1, nom_entreprise="Ma Boite SAS", siret=SIRET_EMETTEUR)


def _facture_validee(
    statut: str = "validée",
    type_facture: TypeFacture = TypeFacture.FACTURE,
    siret_emetteur: str | None = SIRET_EMETTEUR,
    siret_destinataire: str | None = SIRET_DESTINATAIRE,
    snapshot_client: dict[str, Any] | None = None,
    total_ht: Decimal = Decimal("100.00"),
    total_tva: Decimal = Decimal("20.00"),
    total_ttc: Decimal = Decimal("120.00"),
) -> Facture:
    facture = Facture(
        id=42,
        id_entreprise=1,
        id_createur=1,
        id_client=7,
        numero_facture="FAC-202607-0001",
        date_emission=date(2026, 7, 30),
        devise="EUR",
        type_facture=type_facture,
        id_statut=2,
        siret_emetteur=siret_emetteur,
        siret_destinataire=siret_destinataire,
        snapshot_client=(
            snapshot_client
            if snapshot_client is not None
            else {"raison_sociale": "Client Test SARL"}
        ),
        total_ht=total_ht,
        total_tva=total_tva,
        total_ttc=total_ttc,
    )
    facture.statut_ref = StatutFacture(id=2, libelle=statut)
    return facture


def _app(session: _FakeSession) -> FastAPI:
    app = FastAPI()
    app.include_router(factures_router)
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: Utilisateur(
        id=1,
        nom="Test",
        prenom="User",
        email="test@example.com",
        hash_mot_de_passe="x",  # pragma: allowlist secret
    )
    app.dependency_overrides[verify_tenant_access] = lambda: 1
    return app


async def _rapport(facture: Facture | None, chemin: str = "conformite") -> Response:
    """Appelle la route de conformité (ou de génération) avec une facture."""
    session = _FakeSession(results=[facture], gets={(Entreprise, 1): _entreprise()})
    transport = ASGITransport(app=_app(session))
    url = f"/factures/42/facturx/{chemin}" if chemin else "/factures/42/facturx"
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(url)


def _codes(problemes: list[dict[str, Any]]) -> list[str]:
    return [probleme["code"] for probleme in problemes]


# ---------------------------------------------------------------------------
# Route : rapport structuré et garde-fous
# ---------------------------------------------------------------------------


async def test_facture_conforme() -> None:
    """Facture complète : conforme, aucune erreur, avertissements informatifs."""
    response = await _rapport(_facture_validee())
    assert response.status_code == 200

    rapport = response.json()
    assert rapport["conforme"] is True
    assert rapport["erreurs"] == []
    # Limites connues du MVP, toujours signalées.
    assert _codes(rapport["avertissements"]) == [
        "seller_name_not_snapshotted",
        "seller_country_defaulted",
    ]


async def test_siret_emetteur_manquant() -> None:
    """SIRET émetteur absent : erreur bloquante listée."""
    response = await _rapport(_facture_validee(siret_emetteur=None))
    rapport = response.json()
    assert rapport["conforme"] is False
    assert "seller_siret_missing" in _codes(rapport["erreurs"])


async def test_raison_sociale_destinataire_absente() -> None:
    """Snapshot client sans raison sociale : erreur bloquante."""
    response = await _rapport(_facture_validee(snapshot_client={"ville": "Paris"}))
    rapport = response.json()
    assert rapport["conforme"] is False
    assert "buyer_name_missing" in _codes(rapport["erreurs"])


async def test_montants_incoherents() -> None:
    """TTC ≠ HT + TVA au-delà de la tolérance d'arrondi : erreur."""
    response = await _rapport(_facture_validee(total_ttc=Decimal("120.02")))
    rapport = response.json()
    assert rapport["conforme"] is False
    assert "totals_mismatch" in _codes(rapport["erreurs"])


async def test_ecart_arrondi_tolere() -> None:
    """Un écart d'exactement 0,01 (arrondi) ne déclenche pas d'erreur."""
    response = await _rapport(_facture_validee(total_ttc=Decimal("120.01")))
    assert response.json()["conforme"] is True


async def test_multi_problemes_tous_listes() -> None:
    """Plusieurs problèmes simultanés : tous listés, pas d'arrêt au premier."""
    response = await _rapport(
        _facture_validee(
            siret_emetteur=None,
            snapshot_client={},
            total_ttc=Decimal("999.99"),
        )
    )
    rapport = response.json()
    assert rapport["conforme"] is False
    codes = _codes(rapport["erreurs"])
    assert "seller_siret_missing" in codes
    assert "buyer_name_missing" in codes
    assert "totals_mismatch" in codes
    assert len(codes) == 3


async def test_siret_destinataire_absent_avertissement() -> None:
    """SIRET destinataire absent : simple avertissement, facture conforme."""
    response = await _rapport(_facture_validee(siret_destinataire=None))
    rapport = response.json()
    assert rapport["conforme"] is True
    assert "buyer_siret_missing" in _codes(rapport["avertissements"])


async def test_refus_brouillon() -> None:
    """Pas de rapport sur un brouillon (données non figées) : 409."""
    response = await _rapport(_facture_validee(statut="Brouillon"))
    assert response.status_code == 409
    assert "brouillon" in response.json()["detail"].lower()


async def test_facture_hors_perimetre_introuvable() -> None:
    """Facture inexistante ou d'une autre entreprise : 404 (isolation tenant)."""
    response = await _rapport(None)
    assert response.status_code == 404


async def test_generation_partage_les_regles() -> None:
    """La génération applique les mêmes règles : 409 sur montants incohérents."""
    response = await _rapport(_facture_validee(total_ttc=Decimal("999.99")), chemin="")
    assert response.status_code == 409
    assert "conforme" in response.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Règles unitaires : SIRET, signe des montants
# ---------------------------------------------------------------------------


def test_siret_treize_chiffres_invalide() -> None:
    rapport = check_facturx_minimum(
        _facture_validee(siret_emetteur="1234567890001"), _entreprise()
    )
    assert not rapport.conforme
    assert "seller_siret_invalid" in [e.code for e in rapport.erreurs]


def test_siret_luhn_invalide_mode_strict(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mode strict (défaut production) : clé de Luhn incorrecte = erreur bloquante."""
    monkeypatch.setattr(settings, "SIRET_LUHN_STRICT", True)
    rapport = check_facturx_minimum(
        _facture_validee(siret_destinataire="98765432100022"), _entreprise()
    )
    assert not rapport.conforme
    assert "buyer_siret_luhn_invalid" in [e.code for e in rapport.erreurs]


def test_siret_emetteur_luhn_invalide_mode_strict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Le SIRET émetteur porte son propre code Luhn, distinct du format."""
    monkeypatch.setattr(settings, "SIRET_LUHN_STRICT", True)
    rapport = check_facturx_minimum(
        _facture_validee(siret_emetteur="12345678900016"), _entreprise()
    )
    assert not rapport.conforme
    assert "seller_siret_luhn_invalid" in [e.code for e in rapport.erreurs]


def test_siret_luhn_invalide_mode_relache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mode relâché (sandbox) : clé incorrecte = avertissement, facture conforme."""
    monkeypatch.setattr(settings, "SIRET_LUHN_STRICT", False)
    rapport = check_facturx_minimum(
        _facture_validee(siret_destinataire="98765432100022"), _entreprise()
    )
    assert rapport.conforme
    assert "buyer_siret_luhn_invalid" in [a.code for a in rapport.avertissements]


def test_format_siret_reste_bloquant_en_mode_relache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Le relâchement ne concerne que la clé de Luhn, jamais le format."""
    monkeypatch.setattr(settings, "SIRET_LUHN_STRICT", False)
    rapport = check_facturx_minimum(
        _facture_validee(siret_emetteur="1234567890001"), _entreprise()
    )
    assert not rapport.conforme
    assert "seller_siret_invalid" in [e.code for e in rapport.erreurs]


def test_siret_la_poste_exempte_de_luhn() -> None:
    """Les SIRET La Poste (SIREN 356000000) sont exemptés de la clé de Luhn."""
    rapport = check_facturx_minimum(
        _facture_validee(siret_destinataire=SIRET_LA_POSTE), _entreprise()
    )
    assert rapport.conforme


def test_avoir_negatif_conforme() -> None:
    """Un avoir est stocké en négatif : signe attendu, conforme."""
    rapport = check_facturx_minimum(
        _facture_validee(
            type_facture=TypeFacture.AVOIR,
            total_ht=Decimal("-100.00"),
            total_tva=Decimal("-20.00"),
            total_ttc=Decimal("-120.00"),
        ),
        _entreprise(),
    )
    assert rapport.conforme


def test_facture_negative_erreur() -> None:
    """Une facture (non avoir) en négatif : erreur de signe."""
    rapport = check_facturx_minimum(
        _facture_validee(
            total_ht=Decimal("-100.00"),
            total_tva=Decimal("-20.00"),
            total_ttc=Decimal("-120.00"),
        ),
        _entreprise(),
    )
    assert not rapport.conforme
    assert "totals_sign_invalid" in [e.code for e in rapport.erreurs]


def test_avoir_positif_erreur() -> None:
    """Un avoir stocké en positif : erreur de signe."""
    rapport = check_facturx_minimum(
        _facture_validee(type_facture=TypeFacture.AVOIR), _entreprise()
    )
    assert not rapport.conforme
    assert "totals_sign_invalid" in [e.code for e in rapport.erreurs]


def test_total_ttc_zero_avertissement() -> None:
    """Totaux à zéro : conforme mais signalé."""
    rapport = check_facturx_minimum(
        _facture_validee(
            total_ht=Decimal("0.00"),
            total_tva=Decimal("0.00"),
            total_ttc=Decimal("0.00"),
        ),
        _entreprise(),
    )
    assert rapport.conforme
    assert "total_amount_zero" in [a.code for a in rapport.avertissements]


def test_devise_invalide() -> None:
    facture = _facture_validee()
    facture.devise = "euro"
    rapport = check_facturx_minimum(facture, _entreprise())
    assert not rapport.conforme
    assert "currency_invalid" in [e.code for e in rapport.erreurs]
