"""Tests du compteur d'indisponibilité des services externes.

L'instrumentation httpx n'enregistre aucune métrique quand la connexion
échoue (l'exception est relevée avant l'enregistrement de l'histogramme) :
le compteur ``external_api.unavailable`` comble ce trou. Vérifie qu'il
s'incrémente sur les échecs de transport de chacun des clients sortants
(SIRENE, API IA, PISTE/Chorus Pro) — et jamais sur une réponse HTTP
d'erreur, déjà comptée par l'instrumentation — et qu'il reste no-op quand
les métriques sont désactivées. Aucun appel réseau réel.
"""

from pathlib import Path
from typing import Any

import httpx
import pytest
import src.core.telemetry as telemetry
from src.core.config import settings
from src.core.telemetry import record_external_api_unavailable
from src.integrations.chorus_pro.auth import PisteAuthClient
from src.integrations.chorus_pro.client import ChorusProClient
from src.integrations.chorus_pro.exceptions import (
    ChorusProAuthError,
    ChorusProError,
)
from src.integrations.ia_api.client import trigger_extraction
from src.integrations.siren_gouv.client import get_company_by_identifier


class FauxCompteur:
    """Double du compteur OTel : mémorise les incréments et leurs labels."""

    def __init__(self) -> None:
        self.increments: list[dict[str, str]] = []

    def add(self, amount: int, attributes: dict[str, str] | None = None) -> None:
        assert amount == 1
        self.increments.append(dict(attributes or {}))


@pytest.fixture
def faux_compteur(monkeypatch: pytest.MonkeyPatch) -> FauxCompteur:
    """Substitue un compteur factice au compteur module de la télémétrie."""
    compteur = FauxCompteur()
    monkeypatch.setattr(telemetry, "_external_api_unavailable_counter", compteur)
    return compteur


class TestRecordExternalApiUnavailable:
    """La fonction d'enregistrement elle-même."""

    def test_no_op_si_metriques_desactivees(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Sans compteur (métriques désactivées, l'état par défaut), aucun
        effet et surtout aucune exception."""
        monkeypatch.setattr(telemetry, "_external_api_unavailable_counter", None)
        record_external_api_unavailable("sirene")

    def test_increment_avec_label_service(self, faux_compteur: FauxCompteur) -> None:
        record_external_api_unavailable("ia_api")
        assert faux_compteur.increments == [{"service": "ia_api"}]


# ---------------------------------------------------------------------------
# Client SIRENE
# ---------------------------------------------------------------------------


def _force_transport_sirene(
    monkeypatch: pytest.MonkeyPatch,
    handler: "Any",
) -> None:
    """Injecte un transport factice dans le client SIRENE, qui crée son
    ``AsyncClient`` en interne (pas de paramètre d'injection)."""
    original = httpx.AsyncClient

    def fake_async_client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = httpx.MockTransport(handler)
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", fake_async_client)


async def test_sirene_connexion_refusee_incremente(
    monkeypatch: pytest.MonkeyPatch, faux_compteur: FauxCompteur
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connexion refusée", request=request)

    _force_transport_sirene(monkeypatch, handler)
    result = await get_company_by_identifier("34021612133798")

    assert result is None
    assert faux_compteur.increments == [{"service": "sirene"}]


async def test_sirene_reponse_5xx_n_incremente_pas(
    monkeypatch: pytest.MonkeyPatch, faux_compteur: FauxCompteur
) -> None:
    """Une réponse 5xx est déjà comptée par l'instrumentation httpx : le
    compteur ne doit pas la compter double."""
    _force_transport_sirene(monkeypatch, lambda request: httpx.Response(500))
    result = await get_company_by_identifier("34021612133798")

    assert result is None
    assert faux_compteur.increments == []


# ---------------------------------------------------------------------------
# Client API IA
# ---------------------------------------------------------------------------


def _fichier_pdf(tmp_path: Path) -> Path:
    file_path = tmp_path / "facture.pdf"
    file_path.write_bytes(b"%PDF-1.4 contenu factice")
    return file_path


async def test_ia_api_connexion_refusee_incremente(
    tmp_path: Path, faux_compteur: FauxCompteur
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connexion refusée", request=request)

    accepted = await trigger_extraction(
        _fichier_pdf(tmp_path), 42, transport=httpx.MockTransport(handler)
    )

    assert accepted is False
    assert faux_compteur.increments == [{"service": "ia_api"}]


async def test_ia_api_reponse_5xx_n_incremente_pas(
    tmp_path: Path, faux_compteur: FauxCompteur
) -> None:
    accepted = await trigger_extraction(
        _fichier_pdf(tmp_path),
        42,
        transport=httpx.MockTransport(lambda request: httpx.Response(500)),
    )

    assert accepted is False
    assert faux_compteur.increments == []


# ---------------------------------------------------------------------------
# Clients PISTE / Chorus Pro
# ---------------------------------------------------------------------------


@pytest.fixture
def credentials_chorus(monkeypatch: pytest.MonkeyPatch) -> None:
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


async def test_piste_connexion_refusee_incremente(
    credentials_chorus: None, faux_compteur: FauxCompteur
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connexion refusée", request=request)

    auth = PisteAuthClient(transport=httpx.MockTransport(handler))
    with pytest.raises(ChorusProAuthError):
        await auth.get_token()

    assert faux_compteur.increments == [{"service": "chorus_pro"}]


async def test_piste_token_refuse_n_incremente_pas(
    credentials_chorus: None, faux_compteur: FauxCompteur
) -> None:
    """Un refus HTTP (serveur joignable) n'est pas une indisponibilité."""
    auth = PisteAuthClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(401))
    )
    with pytest.raises(ChorusProAuthError):
        await auth.get_token()

    assert faux_compteur.increments == []


async def test_chorus_connexion_refusee_incremente(
    credentials_chorus: None, faux_compteur: FauxCompteur
) -> None:
    """OAuth PISTE répond, mais Chorus Pro est injoignable : un incrément."""

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == settings.CHORUS_OAUTH_URL:
            return httpx.Response(
                200, json={"access_token": "token-1", "expires_in": 3600}
            )
        raise httpx.ConnectError("connexion refusée", request=request)

    client = ChorusProClient(transport=httpx.MockTransport(handler))
    with pytest.raises(ChorusProError):
        await client.deposer_flux_facturx(b"%PDF-1.4", "facture.pdf")

    assert faux_compteur.increments == [{"service": "chorus_pro"}]
