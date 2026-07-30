"""Tests du client OAuth2 PISTE (`PisteAuthClient`).

Aucun appel réseau réel : les échanges passent par un ``httpx.MockTransport``
injecté, et l'horloge du cache est simulée pour vérifier la mise en cache du
token, sa péremption (marge de 60 s déduite) et son invalidation.
"""

import httpx
import pytest
from src.core.config import settings
from src.integrations.chorus_pro.auth import PisteAuthClient
from src.integrations.chorus_pro.exceptions import (
    ChorusProAuthError,
    ChorusProConfigurationError,
)


class _Horloge:
    """Horloge monotone factice, avançable manuellement."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture(autouse=True)
def _credentials_piste(monkeypatch: pytest.MonkeyPatch) -> None:
    """Renseigne des credentials PISTE factices pour tous les tests."""
    monkeypatch.setattr(settings, "CHORUS_PISTE_CLIENT_ID", "client-id-test")
    monkeypatch.setattr(
        settings,
        "CHORUS_PISTE_CLIENT_SECRET",
        "client-secret-test",  # pragma: allowlist secret
    )
    monkeypatch.setattr(
        settings,
        "CHORUS_OAUTH_URL",
        "https://sandbox-oauth.piste.gouv.fr/api/oauth/token",
    )


def _token_transport(
    requests: list[httpx.Request], *, expires_in: int = 3600
) -> httpx.MockTransport:
    """Transport factice : capture les requêtes et sert un token numéroté."""

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "access_token": f"tok-{len(requests)}",
                "token_type": "Bearer",
                "expires_in": expires_in,
            },
        )

    return httpx.MockTransport(handler)


async def test_obtention_token_client_credentials() -> None:
    """La requête token part en form-urlencoded avec le grant et le scope."""
    requests: list[httpx.Request] = []
    client = PisteAuthClient(transport=_token_transport(requests))

    assert await client.get_token() == "tok-1"

    request = requests[0]
    assert str(request.url) == settings.CHORUS_OAUTH_URL
    body = request.read().decode()
    assert "grant_type=client_credentials" in body
    assert "client_id=client-id-test" in body
    assert "client_secret=client-secret-test" in body
    assert "scope=openid" in body


async def test_token_mis_en_cache() -> None:
    """Deux appels rapprochés ne déclenchent qu'une seule requête OAuth."""
    requests: list[httpx.Request] = []
    client = PisteAuthClient(transport=_token_transport(requests))

    premier = await client.get_token()
    second = await client.get_token()

    assert premier == second == "tok-1"
    assert len(requests) == 1


async def test_token_rafraichi_a_expiration() -> None:
    """Passé l'``expires_in`` (marge déduite), un token neuf est demandé."""
    requests: list[httpx.Request] = []
    horloge = _Horloge()
    client = PisteAuthClient(transport=_token_transport(requests), clock=horloge)

    assert await client.get_token() == "tok-1"

    # Juste avant la fenêtre de marge (3600 - 60 s) : le cache sert encore.
    horloge.now += 3539.0
    assert await client.get_token() == "tok-1"
    assert len(requests) == 1

    # Dans la marge de sécurité : le token est considéré périmé.
    horloge.now += 2.0
    assert await client.get_token() == "tok-2"
    assert len(requests) == 2


async def test_invalidation_force_un_token_neuf() -> None:
    """`invalidate()` purge le cache : l'appel suivant redemande un token."""
    requests: list[httpx.Request] = []
    client = PisteAuthClient(transport=_token_transport(requests))

    assert await client.get_token() == "tok-1"
    client.invalidate()
    assert await client.get_token() == "tok-2"
    assert len(requests) == 2


async def test_refus_piste_leve_auth_error() -> None:
    """Un statut HTTP d'erreur du serveur OAuth lève ``ChorusProAuthError``."""
    transport = httpx.MockTransport(
        lambda request: httpx.Response(401, json={"error": "invalid_client"})
    )
    client = PisteAuthClient(transport=transport)

    with pytest.raises(ChorusProAuthError):
        await client.get_token()


async def test_timeout_piste_leve_auth_error() -> None:
    """Une erreur réseau (timeout) lève ``ChorusProAuthError``."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timeout")

    client = PisteAuthClient(transport=httpx.MockTransport(handler))

    with pytest.raises(ChorusProAuthError):
        await client.get_token()


async def test_credentials_absents_leve_configuration_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sans client_id PISTE configuré, aucun appel réseau n'est tenté."""
    monkeypatch.setattr(settings, "CHORUS_PISTE_CLIENT_ID", None)
    client = PisteAuthClient(transport=_token_transport([]))

    with pytest.raises(ChorusProConfigurationError):
        await client.get_token()
