"""Tests du jeton d'identité Google pour l'IAM Cloud Run (`gcp_identity`).

Aucune dépendance à l'environnement : l'interrupteur `IA_API_IAM_AUTH_ENABLED`
est posé par monkeypatch sur ``settings`` et l'obtention du jeton
(``fetch_id_token``) est remplacée par une factice — le serveur de métadonnées
n'est jamais contacté. Le cache module est purgé entre chaque test par une
fixture autouse, sans quoi un jeton posé par un test fuirait dans le suivant.
"""

import base64
import json
import time
from collections.abc import Iterator
from typing import Any

import pytest
from src.core.config import settings
from src.integrations import gcp_identity
from src.integrations.gcp_identity import (
    IdentityTokenError,
    serverless_authorization_header,
)


def _jwt_factice(exp: float, marqueur: str = "jeton") -> str:
    """Construit un pseudo-JWT dont seule la claim `exp` est lisible."""
    payload = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode())
    return f"entete.{payload.rstrip(b'=').decode()}.{marqueur}"


@pytest.fixture(autouse=True)
def _cache_vierge() -> Iterator[None]:
    """Purge le cache module avant et après chaque test."""
    gcp_identity._cached_token = None
    gcp_identity._cached_expiry = 0.0
    yield
    gcp_identity._cached_token = None
    gcp_identity._cached_expiry = 0.0


async def test_desactive_renvoie_vide_sans_obtention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Désactivé (défaut) : dictionnaire vide, aucun jeton demandé."""
    monkeypatch.setattr(settings, "IA_API_IAM_AUTH_ENABLED", False)

    def fetch_interdit(*args: Any, **kwargs: Any) -> str:
        raise AssertionError("fetch_id_token ne doit pas être appelé désactivé")

    monkeypatch.setattr(gcp_identity, "fetch_id_token", fetch_interdit)

    assert await serverless_authorization_header() == {}


async def test_active_renvoie_en_tete_bearer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Activé : l'en-tête X-Serverless-Authorization porte le jeton en Bearer."""
    monkeypatch.setattr(settings, "IA_API_IAM_AUTH_ENABLED", True)
    jeton = _jwt_factice(time.time() + 3600)
    monkeypatch.setattr(gcp_identity, "fetch_id_token", lambda *a: jeton)

    header = await serverless_authorization_header()

    assert header == {"X-Serverless-Authorization": f"Bearer {jeton}"}


async def test_audience_est_url_api_ia(monkeypatch: pytest.MonkeyPatch) -> None:
    """L'audience demandée est l'URL canonique du service appelé."""
    monkeypatch.setattr(settings, "IA_API_IAM_AUTH_ENABLED", True)
    audiences: list[str] = []

    def fetch(request: Any, audience: str) -> str:
        audiences.append(audience)
        return _jwt_factice(time.time() + 3600)

    monkeypatch.setattr(gcp_identity, "fetch_id_token", fetch)

    await serverless_authorization_header()

    assert audiences == [settings.IA_API_BASE_URL]


async def test_jeton_valide_mis_en_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Deux appels consécutifs ne déclenchent qu'une seule obtention."""
    monkeypatch.setattr(settings, "IA_API_IAM_AUTH_ENABLED", True)
    obtentions: list[str] = []

    def fetch(*args: Any) -> str:
        jeton = _jwt_factice(time.time() + 3600, marqueur=f"n{len(obtentions)}")
        obtentions.append(jeton)
        return jeton

    monkeypatch.setattr(gcp_identity, "fetch_id_token", fetch)

    premier = await serverless_authorization_header()
    second = await serverless_authorization_header()

    assert len(obtentions) == 1
    assert premier == second


async def test_jeton_pres_expiration_renouvele(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un jeton à moins de 5 minutes de l'expiration est renouvelé."""
    monkeypatch.setattr(settings, "IA_API_IAM_AUTH_ENABLED", True)
    # Premier jeton mourant (expire dans 60 s, sous la marge de 300 s),
    # second jeton frais : le deuxième appel doit obtenir le second.
    jetons = iter(
        [
            _jwt_factice(time.time() + 60, marqueur="mourant"),
            _jwt_factice(time.time() + 3600, marqueur="frais"),
        ]
    )
    monkeypatch.setattr(gcp_identity, "fetch_id_token", lambda *a: next(jetons))

    premier = await serverless_authorization_header()
    second = await serverless_authorization_header()

    assert premier["X-Serverless-Authorization"].endswith("mourant")
    assert second["X-Serverless-Authorization"].endswith("frais")


async def test_exp_illisible_repli_une_heure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Une claim `exp` illisible n'empêche rien : repli sur une heure de vie."""
    monkeypatch.setattr(settings, "IA_API_IAM_AUTH_ENABLED", True)
    monkeypatch.setattr(gcp_identity, "fetch_id_token", lambda *a: "pas-un-jwt")

    avant = time.time()
    header = await serverless_authorization_header()

    assert header == {"X-Serverless-Authorization": "Bearer pas-un-jwt"}
    # Expiration planifiée ≈ maintenant + 1 h (repli), à la seconde près.
    assert gcp_identity._cached_expiry == pytest.approx(avant + 3600.0, abs=5.0)


async def test_echec_obtention_leve_identity_token_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un échec d'obtention est traduit en IdentityTokenError, cache intact."""
    monkeypatch.setattr(settings, "IA_API_IAM_AUTH_ENABLED", True)

    def fetch_en_echec(*args: Any) -> str:
        raise RuntimeError("serveur de métadonnées injoignable")

    monkeypatch.setattr(gcp_identity, "fetch_id_token", fetch_en_echec)

    with pytest.raises(IdentityTokenError):
        await serverless_authorization_header()

    assert gcp_identity._cached_token is None
