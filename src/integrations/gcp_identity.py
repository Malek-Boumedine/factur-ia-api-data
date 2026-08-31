"""Jeton d'identité Google pour l'authentification IAM de Cloud Run.

En production, l'API IA n'est pas publique : Cloud Run n'accepte que les
appels portant un jeton d'identité Google d'un compte autorisé
(`roles/run.invoker`). Le jeton voyage dans `X-Serverless-Authorization`,
prévu par Cloud Run pour ce cas : la plateforme le vérifie puis le retire
avant de transmettre la requête — il n'entre jamais dans le conteneur appelé,
donc ne peut fuiter ni dans ses logs ni dans son instrumentation. L'en-tête
`Authorization` reste libre (l'authentification applicative entre services
passe par `X-OCR-Secret-Token`).

Le jeton est obtenu via `google-auth` auprès du serveur de métadonnées de
Cloud Run (aucune clé), avec pour audience l'URL du service appelé
(`IA_API_BASE_URL` — l'URL canonique fournie par Terraform : un jeton signé
pour un autre format d'URL est rejeté comme un jeton absent, sans erreur
visible côté appelant). Valable une heure, il est mis en cache au niveau du
module et renouvelé avec une marge d'avance ; l'obtention, bloquante, part
dans un thread pour ne jamais geler la boucle d'événements, et le verrou
asynchrone évite les obtentions concurrentes.

Interrupteur : `IA_API_IAM_AUTH_ENABLED` (défaut faux). Hors production
(dev, test), le module ne fait strictement rien — pas de serveur de
métadonnées en local, et l'API IA locale n'exige aucun jeton.
"""

import asyncio
import base64
import binascii
import json
import time

from google.auth.transport.requests import Request
from google.oauth2.id_token import fetch_id_token
from loguru import logger

from src.core.config import settings

# Marge de renouvellement : un jeton à moins de 5 minutes de son expiration
# est considéré périmé, pour ne jamais envoyer un jeton mourant en vol.
_REFRESH_MARGIN = 300.0

# Durée de vie supposée (une heure, standard Google) si la claim `exp` du
# jeton reçu s'avère illisible — cas théorique, on reste défensif.
_FALLBACK_LIFETIME = 3600.0

# Cache module-niveau : partagé par toutes les tâches de la boucle uvicorn.
_lock = asyncio.Lock()
_cached_token: str | None = None
_cached_expiry = 0.0  # epoch (secondes), 0 = aucun jeton en cache


class IdentityTokenError(Exception):
    """Jeton d'identité Google impossible à obtenir (IAM activé)."""


async def serverless_authorization_header() -> dict[str, str]:
    """Construit l'en-tête d'authentification IAM Cloud Run, si activé.

    Point d'entrée unique du module, appelé par le client IA à chaque
    construction d'en-têtes. Quand `IA_API_IAM_AUTH_ENABLED` est faux (dev,
    test), renvoie un dictionnaire vide sans la moindre tentative
    d'obtention de jeton.

    Returns:
        dict[str, str]: `{"X-Serverless-Authorization": "Bearer <jeton>"}`
        si l'authentification IAM est activée, `{}` sinon.

    Raises:
        IdentityTokenError: Jeton impossible à obtenir alors que
            l'authentification IAM est activée (l'API IA est de fait
            injoignable ; l'appelant traite ce cas comme un échec réseau).
    """
    if not settings.IA_API_IAM_AUTH_ENABLED:
        return {}
    return {"X-Serverless-Authorization": f"Bearer {await _get_identity_token()}"}


async def _get_identity_token() -> str:
    """Renvoie un jeton d'identité valide, depuis le cache ou fraîchement obtenu.

    Le verrou couvre la lecture ET le renouvellement : une seule tâche
    interroge le serveur de métadonnées, les autres attendent le jeton frais
    plutôt que de déclencher des obtentions concurrentes.

    Returns:
        str: Jeton d'identité Google encore valide au moins `_REFRESH_MARGIN`
        secondes.

    Raises:
        IdentityTokenError: Échec de l'obtention auprès du serveur de
            métadonnées.
    """
    global _cached_token, _cached_expiry
    async with _lock:
        now = time.time()
        if _cached_token is not None and now < _cached_expiry - _REFRESH_MARGIN:
            return _cached_token

        token = await asyncio.to_thread(_fetch_identity_token)
        _cached_token = token
        _cached_expiry = _read_expiry(token, now)
        return token


def _fetch_identity_token() -> str:
    """Obtient un jeton d'identité auprès du serveur de métadonnées Cloud Run.

    L'audience est l'URL du service appelé (`IA_API_BASE_URL`) : c'est elle
    que Cloud Run vérifie côté API IA. Aucune clé ni fichier de credentials :
    `google-auth` s'appuie sur l'identité du compte de service du conteneur.
    Bloquant : à appeler via `asyncio.to_thread`.

    Returns:
        str: Jeton d'identité (JWT signé par Google), valable une heure.

    Raises:
        IdentityTokenError: Toute erreur d'obtention (serveur de métadonnées
            injoignable, identité absente) — journalisée puis traduite dans
            l'exception que le client IA sait traiter.
    """
    audience = settings.IA_API_BASE_URL
    try:
        # google-auth est marqué py.typed mais laisse cette fonction sans
        # annotations : l'appel est « untyped » pour mypy strict.
        token: str = fetch_id_token(Request(), audience)  # type: ignore[no-untyped-call]
    except Exception as exc:
        logger.error(
            "Échec d'obtention du jeton d'identité Google (audience {}) : {}",
            audience,
            exc,
        )
        raise IdentityTokenError() from exc
    return token


def _read_expiry(token: str, now: float) -> float:
    """Lit l'expiration (`exp`) dans le payload du jeton, sans vérification.

    Le jeton vient d'être remis par le serveur de métadonnées : aucune raison
    de vérifier sa signature, on ne fait que planifier son renouvellement.

    Args:
        token (str): Jeton d'identité au format JWT. Obligatoire.
        now (float): Horodatage courant (epoch), base du repli si la claim
            est illisible. Obligatoire.

    Returns:
        float: Expiration en secondes epoch — la claim `exp`, ou
        `now + _FALLBACK_LIFETIME` si elle est illisible.
    """
    try:
        payload_b64 = token.split(".")[1]
        # Le base64url des JWT est émis sans padding : on le complète.
        payload_b64 += "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        return float(payload["exp"])
    except (IndexError, KeyError, TypeError, ValueError, binascii.Error):
        logger.warning("Claim `exp` illisible dans le jeton d'identité, repli 1 h.")
        return now + _FALLBACK_LIFETIME
