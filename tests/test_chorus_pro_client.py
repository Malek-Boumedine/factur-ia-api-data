"""Tests du client Chorus Pro (`ChorusProClient.deposer_flux_facturx`).

Aucun appel réseau réel : un ``httpx.MockTransport`` unique sert à la fois le
serveur OAuth PISTE et l'API Chorus Pro (routage par URL). Vérifie la double
authentification (Bearer + cpro-account), l'encodage base64 du PDF, le
contrôle du ``codeRetour`` même sur HTTP 200 et le retry unique sur 401.
"""

import base64
import json
from typing import Any

import httpx
import pytest
from src.core.config import settings
from src.integrations.chorus_pro.client import (
    DEPOSER_FLUX_PATH,
    SYNTAXE_FLUX_FACTURX,
    ChorusProClient,
)
from src.integrations.chorus_pro.exceptions import (
    ChorusProDepotError,
    ChorusProError,
)

PDF_FACTICE = b"%PDF-1.4 contenu facture factice"

REPONSE_DEPOT_OK = {
    "codeRetour": 0,
    "libelle": "GCU_MSG_01_000",
    "numeroFluxDepot": "CPP0011117000000000414554",
    "dateDepot": "2026-07-30",
    "syntaxeFlux": "IN_DP_E2_CII_FACTURX",
}


@pytest.fixture(autouse=True)
def _credentials_chorus(monkeypatch: pytest.MonkeyPatch) -> None:
    """Renseigne des credentials PISTE et Chorus Pro factices."""
    monkeypatch.setattr(settings, "CHORUS_PISTE_CLIENT_ID", "client-id-test")
    monkeypatch.setattr(
        settings,
        "CHORUS_PISTE_CLIENT_SECRET",
        "client-secret-test",  # pragma: allowlist secret
    )
    monkeypatch.setattr(settings, "CHORUS_TECH_LOGIN", "TECH_1_test@cpro.fr")
    monkeypatch.setattr(
        settings,
        "CHORUS_TECH_PASSWORD",
        "mdp-technique",  # pragma: allowlist secret
    )
    monkeypatch.setattr(
        settings,
        "CHORUS_OAUTH_URL",
        "https://sandbox-oauth.piste.gouv.fr/api/oauth/token",
    )
    monkeypatch.setattr(
        settings, "CHORUS_BASE_URL", "https://sandbox-api.piste.gouv.fr"
    )


def _transport(
    depot_responses: list[httpx.Response],
    *,
    oauth_requests: list[httpx.Request] | None = None,
    depot_requests: list[httpx.Request] | None = None,
) -> httpx.MockTransport:
    """Transport factice routant OAuth PISTE et dépôt Chorus Pro.

    Les réponses de dépôt sont dépilées dans l'ordre (permet de simuler un
    401 suivi d'un succès) ; les tokens servis sont numérotés.
    """
    compteur_tokens = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == settings.CHORUS_OAUTH_URL:
            if oauth_requests is not None:
                oauth_requests.append(request)
            compteur_tokens["n"] += 1
            return httpx.Response(
                200,
                json={
                    "access_token": f"tok-{compteur_tokens['n']}",
                    "expires_in": 3600,
                },
            )
        assert str(request.url) == f"{settings.CHORUS_BASE_URL}{DEPOSER_FLUX_PATH}"
        if depot_requests is not None:
            depot_requests.append(request)
        return depot_responses.pop(0)

    return httpx.MockTransport(handler)


async def test_depot_double_auth_et_base64() -> None:
    """Le dépôt porte la double auth et le PDF encodé en base64."""
    depot_requests: list[httpx.Request] = []
    transport = _transport(
        [httpx.Response(200, json=REPONSE_DEPOT_OK)], depot_requests=depot_requests
    )
    client = ChorusProClient(transport=transport)

    depot = await client.deposer_flux_facturx(
        PDF_FACTICE, "FAC-202607-0001-facturx.pdf"
    )

    assert depot.numero_flux_depot == "CPP0011117000000000414554"
    assert depot.date_depot == "2026-07-30"
    assert depot.syntaxe_flux == "IN_DP_E2_CII_FACTURX"

    request = depot_requests[0]
    # Double authentification : token Bearer PISTE + compte technique en base64.
    assert request.headers["Authorization"] == "Bearer tok-1"
    attendu = base64.b64encode(b"TECH_1_test@cpro.fr:mdp-technique").decode("ascii")
    assert request.headers["cpro-account"] == attendu

    body: dict[str, Any] = json.loads(request.read())
    assert base64.b64decode(body["fichierFlux"]) == PDF_FACTICE
    assert body["nomFichier"] == "FAC-202607-0001-facturx.pdf"
    assert body["syntaxeFlux"] == SYNTAXE_FLUX_FACTURX
    assert body["avecSignature"] is False


async def test_code_retour_non_nul_sur_http_200() -> None:
    """Un HTTP 200 avec ``codeRetour != 0`` est une erreur métier de dépôt."""
    transport = _transport(
        [
            httpx.Response(
                200,
                json={"codeRetour": 135, "libelle": "Syntaxe de flux inconnue"},
            )
        ]
    )
    client = ChorusProClient(transport=transport)

    with pytest.raises(ChorusProDepotError) as excinfo:
        await client.deposer_flux_facturx(PDF_FACTICE, "facture.pdf")

    assert excinfo.value.code_retour == 135
    assert excinfo.value.libelle == "Syntaxe de flux inconnue"


async def test_retry_unique_sur_401_avec_token_neuf() -> None:
    """Un 401 invalide le cache : l'appel est rejoué une fois, token neuf."""
    depot_requests: list[httpx.Request] = []
    oauth_requests: list[httpx.Request] = []
    transport = _transport(
        [httpx.Response(401), httpx.Response(200, json=REPONSE_DEPOT_OK)],
        oauth_requests=oauth_requests,
        depot_requests=depot_requests,
    )
    client = ChorusProClient(transport=transport)

    depot = await client.deposer_flux_facturx(PDF_FACTICE, "facture.pdf")

    assert depot.numero_flux_depot == "CPP0011117000000000414554"
    assert len(oauth_requests) == 2
    assert depot_requests[0].headers["Authorization"] == "Bearer tok-1"
    assert depot_requests[1].headers["Authorization"] == "Bearer tok-2"


async def test_deux_401_consecutifs_levent_erreur() -> None:
    """Le retry sur 401 est unique : un second 401 remonte en erreur."""
    transport = _transport([httpx.Response(401), httpx.Response(401)])
    client = ChorusProClient(transport=transport)

    with pytest.raises(ChorusProError):
        await client.deposer_flux_facturx(PDF_FACTICE, "facture.pdf")


async def test_erreur_http_leve_chorus_error() -> None:
    """Un statut HTTP d'erreur (hors 401) lève ``ChorusProError``."""
    transport = _transport([httpx.Response(500)])
    client = ChorusProClient(transport=transport)

    with pytest.raises(ChorusProError):
        await client.deposer_flux_facturx(PDF_FACTICE, "facture.pdf")


async def test_reponse_sans_numero_flux() -> None:
    """``codeRetour`` 0 sans ``numeroFluxDepot`` : réponse inexploitable."""
    transport = _transport(
        [httpx.Response(200, json={"codeRetour": 0, "libelle": "GCU_MSG_01_000"})]
    )
    client = ChorusProClient(transport=transport)

    with pytest.raises(ChorusProError):
        await client.deposer_flux_facturx(PDF_FACTICE, "facture.pdf")
