"""Tests de la normalisation des SIRET/SIREN sur tous les points d'entrée.

Un identifiant saisi ou collé au format d'affichage courant (espaces normaux,
insécables ou fines, points, tirets) doit être ramené à la forme canonique
« chiffres seuls » partout où un SIRET/SIREN entre dans l'API : recherche
SIRENE, fiches client, onboarding et administration d'entreprise, brouillons
de facture, webhook OCR. Source unique : ``src.core.siret``.
"""

from decimal import Decimal
from typing import Any
from urllib.parse import quote

import pytest
import src.clients.router as clients_router_module
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from src.administration.schemas import EntrepriseAdminUpdate
from src.clients.router import router as clients_router
from src.clients.schemas import ClientCreate, ClientUpdate
from src.core.siret import normalize_siret_input
from src.documents.schemas import OcrWebhookPayload
from src.entreprises.schemas import EntrepriseCreate
from src.factures.schemas import FactureUpdate

SIRET_CANONIQUE = "34021612133798"
SIREN_CANONIQUE = "340216121"

# Séparateurs d'affichage courants : espace normale, insécable (U+00A0),
# fine insécable (U+202F), fine (U+2009), point, tiret.
SEPARATEURS = [" ", " ", " ", " ", ".", "-"]
IDS_SEPARATEURS = ["espace", "insecable", "fine-insecable", "fine", "point", "tiret"]


def _siret_affiche(separateur: str) -> str:
    """SIRET au format d'affichage : ``340 216 121 33798``."""
    return separateur.join(["340", "216", "121", "33798"])


def _client_create(siret: str | None) -> ClientCreate:
    return ClientCreate(
        raison_sociale="ACME", code_postal="75001", ville="Paris", siret=siret
    )


def _payload_ocr(**overrides: Any) -> OcrWebhookPayload:
    defaults: dict[str, Any] = {
        "id_document": 1,
        "score_confiance": Decimal("0.90"),
        "total_ht": Decimal("100.00"),
        "total_tva": Decimal("20.00"),
        "total_ttc": Decimal("120.00"),
    }
    return OcrWebhookPayload(**{**defaults, **overrides})


# ---------------------------------------------------------------------------
# Fonction de normalisation (source unique)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("separateur", SEPARATEURS, ids=IDS_SEPARATEURS)
def test_normalize_siret_input_retire_les_separateurs(separateur: str) -> None:
    assert normalize_siret_input(_siret_affiche(separateur)) == SIRET_CANONIQUE


def test_normalize_siret_input_separateurs_mixtes() -> None:
    assert normalize_siret_input("340 216.121-337 98") == SIRET_CANONIQUE


def test_normalize_siret_input_sans_separateur_inchange() -> None:
    assert normalize_siret_input(SIRET_CANONIQUE) == SIRET_CANONIQUE


# ---------------------------------------------------------------------------
# Route de recherche SIRENE
# ---------------------------------------------------------------------------


def _app_clients() -> FastAPI:
    app = FastAPI()
    app.include_router(clients_router)
    return app


async def _recherche(app: FastAPI, identifiant: str) -> Any:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(
            f"/clients/recherche-sirene/{quote(identifiant, safe='')}"
        )


@pytest.mark.parametrize("separateur", SEPARATEURS, ids=IDS_SEPARATEURS)
async def test_recherche_sirene_siret_avec_separateurs(
    monkeypatch: pytest.MonkeyPatch, separateur: str
) -> None:
    """L'identifiant est normalisé avant l'appel à l'API SIRENE."""
    captures: list[str] = []

    async def fake_lookup(identifiant: str) -> dict[str, Any]:
        captures.append(identifiant)
        return {"siret": identifiant}

    monkeypatch.setattr(clients_router_module, "get_company_by_identifier", fake_lookup)
    response = await _recherche(_app_clients(), _siret_affiche(separateur))

    assert response.status_code == 200
    assert captures == [SIRET_CANONIQUE]


async def test_recherche_sirene_siren_avec_points(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un SIREN (9 chiffres) au format pointé est accepté aussi."""
    captures: list[str] = []

    async def fake_lookup(identifiant: str) -> dict[str, Any]:
        captures.append(identifiant)
        return {"sirene": identifiant}

    monkeypatch.setattr(clients_router_module, "get_company_by_identifier", fake_lookup)
    response = await _recherche(_app_clients(), "340.216.121")

    assert response.status_code == 200
    assert captures == [SIREN_CANONIQUE]


async def test_recherche_sirene_longueur_invalide_400() -> None:
    """Après normalisation, seul 9 ou 14 chiffres est accepté."""
    response = await _recherche(_app_clients(), "340 216")

    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Schémas client
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("separateur", SEPARATEURS, ids=IDS_SEPARATEURS)
def test_client_create_siret_normalise(separateur: str) -> None:
    assert _client_create(_siret_affiche(separateur)).siret == SIRET_CANONIQUE


@pytest.mark.parametrize("separateur", SEPARATEURS, ids=IDS_SEPARATEURS)
def test_client_update_siret_normalise(separateur: str) -> None:
    assert ClientUpdate(siret=_siret_affiche(separateur)).siret == SIRET_CANONIQUE


def test_client_siret_vide_ou_separateurs_vaut_absent() -> None:
    assert _client_create("  ").siret is None
    assert _client_create(None).siret is None


def test_client_siret_non_numerique_422() -> None:
    """Durcissement : un SIRET non numérique n'est plus stocké silencieusement."""
    with pytest.raises(ValidationError):
        _client_create("34A21612133798")


# ---------------------------------------------------------------------------
# Schémas entreprise (onboarding et administration)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("separateur", SEPARATEURS, ids=IDS_SEPARATEURS)
def test_entreprise_create_siret_normalise(separateur: str) -> None:
    entreprise = EntrepriseCreate(
        nom_entreprise="ACME", siret=_siret_affiche(separateur)
    )
    assert entreprise.siret == SIRET_CANONIQUE


def test_entreprise_create_siret_incomplet_422() -> None:
    """La règle stricte (exactement 14 chiffres) tient après normalisation."""
    with pytest.raises(ValidationError):
        EntrepriseCreate(nom_entreprise="ACME", siret="340 216 121")


@pytest.mark.parametrize("separateur", SEPARATEURS, ids=IDS_SEPARATEURS)
def test_entreprise_admin_update_siret_normalise(separateur: str) -> None:
    assert (
        EntrepriseAdminUpdate(siret=_siret_affiche(separateur)).siret == SIRET_CANONIQUE
    )


# ---------------------------------------------------------------------------
# Brouillons de facture
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("separateur", SEPARATEURS, ids=IDS_SEPARATEURS)
def test_facture_update_siret_normalises(separateur: str) -> None:
    facture = FactureUpdate(
        siret_emetteur=_siret_affiche(separateur),
        siret_destinataire=_siret_affiche(separateur),
    )
    assert facture.siret_emetteur == SIRET_CANONIQUE
    assert facture.siret_destinataire == SIRET_CANONIQUE


# ---------------------------------------------------------------------------
# Webhook OCR
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("separateur", SEPARATEURS, ids=IDS_SEPARATEURS)
def test_webhook_ocr_siret_normalises(separateur: str) -> None:
    """Les SIRET du payload OCR sont nettoyés dès la réception : la
    réconciliation de l'émetteur recopie cette valeur telle quelle sur le
    brouillon, elle doit donc déjà être canonique."""
    payload = _payload_ocr(
        siret_emetteur=_siret_affiche(separateur),
        siret_destinataire=_siret_affiche(separateur),
    )
    assert payload.siret_emetteur == SIRET_CANONIQUE
    assert payload.siret_destinataire == SIRET_CANONIQUE


def test_webhook_ocr_siret_illisible_accepte() -> None:
    """Un SIRET illisible passe la porte du webhook (pas de 422) : l'échec
    doit être tracé côté extraction, pas rejeté à la réception."""
    payload = _payload_ocr(siret_emetteur="AB CD")
    assert payload.siret_emetteur == "ABCD"
