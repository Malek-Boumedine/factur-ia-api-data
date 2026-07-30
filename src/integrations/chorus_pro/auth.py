"""Client OAuth2 PISTE (grant ``client_credentials``) avec cache de token.

Le token Bearer délivré par PISTE est valable une heure : il est mis en cache
en mémoire et réutilisé jusqu'à expiration (marge de sécurité déduite), pour
ne pas solliciter le serveur OAuth à chaque appel Chorus Pro. L'horloge
utilisée est ``time.monotonic`` (insensible aux réglages de l'horloge
système) et reste injectable pour les tests.
"""

import asyncio
import time
from collections.abc import Callable

import httpx
from loguru import logger

from src.core.config import settings
from src.integrations.chorus_pro.exceptions import (
    ChorusProAuthError,
    ChorusProConfigurationError,
)

TIMEOUT_SECONDS = 10.0
# Marge déduite de l'``expires_in`` annoncé : un token à moins de 60 s de
# l'expiration est considéré comme périmé (évite un 401 en vol).
EXPIRY_MARGIN_SECONDS = 60.0
# Durée de repli si PISTE omettait ``expires_in`` dans sa réponse.
DEFAULT_EXPIRES_IN_SECONDS = 3600.0


class PisteAuthClient:
    """Obtient et met en cache le token OAuth2 PISTE.

    Le paramètre ``transport`` permet d'injecter un transport httpx factice
    dans les tests ; ``clock`` permet d'y simuler l'écoulement du temps.
    """

    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._transport = transport
        self._clock = clock
        self._token: str | None = None
        self._expires_at = 0.0
        self._lock = asyncio.Lock()

    async def get_token(self) -> str:
        """Renvoie un token valide : celui du cache, ou un token neuf.

        Le verrou évite deux demandes de token concurrentes (une seule
        requête OAuth part, les autres appels réutilisent son résultat).
        """
        async with self._lock:
            if self._token is not None and self._clock() < self._expires_at:
                return self._token
            return await self._fetch_token()

    def invalidate(self) -> None:
        """Purge le cache (token révoqué avant l'heure : 401 Chorus Pro)."""
        self._token = None

    async def _fetch_token(self) -> str:
        """Demande un token neuf à PISTE et le met en cache."""
        client_id = settings.CHORUS_PISTE_CLIENT_ID
        client_secret = settings.CHORUS_PISTE_CLIENT_SECRET
        if not client_id or not client_secret:
            raise ChorusProConfigurationError(
                "Credentials PISTE absents de la configuration "
                "(CHORUS_PISTE_CLIENT_ID / CHORUS_PISTE_CLIENT_SECRET)."
            )

        try:
            async with httpx.AsyncClient(transport=self._transport) as client:
                response = await client.post(
                    settings.CHORUS_OAUTH_URL,
                    data={
                        "grant_type": "client_credentials",
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "scope": "openid",
                    },
                    timeout=TIMEOUT_SECONDS,
                )
        except httpx.HTTPError as exc:
            # Le message httpx ne contient ni body ni credentials : rien ne
            # peut fuiter dans les logs.
            logger.error("Échec de la requête token PISTE : {}", exc)
            raise ChorusProAuthError(
                "Le serveur d'authentification PISTE est injoignable."
            ) from exc

        if response.status_code != 200:
            logger.error("Token PISTE refusé : HTTP {}", response.status_code)
            raise ChorusProAuthError(
                f"PISTE a refusé la demande de token (HTTP {response.status_code})."
            )

        payload = response.json()
        token = payload.get("access_token")
        if not isinstance(token, str) or not token:
            raise ChorusProAuthError("Réponse PISTE sans access_token exploitable.")

        try:
            expires_in = float(payload.get("expires_in", DEFAULT_EXPIRES_IN_SECONDS))
        except (TypeError, ValueError):
            expires_in = DEFAULT_EXPIRES_IN_SECONDS

        self._token = token
        self._expires_at = self._clock() + expires_in - EXPIRY_MARGIN_SECONDS
        return token
