"""Client sortant vers l'API Chorus Pro (via la plateforme PISTE).

Chaque appel porte la double authentification exigée par Chorus Pro :
``Authorization: Bearer <token OAuth2 PISTE>`` et ``cpro-account`` (login et
mot de passe du compte technique encodés en base64, à la volée — le base64
n'étant pas un chiffrement, les identifiants sont stockés en clair dans
l'environnement et jamais journalisés).

Particularité Chorus Pro : une erreur métier peut arriver dans un HTTP 200
avec ``codeRetour != 0`` — le ``codeRetour`` est donc contrôlé sur chaque
réponse, indépendamment du statut HTTP.
"""

import base64
from dataclasses import dataclass

import httpx
from loguru import logger

from src.core.config import settings
from src.integrations.chorus_pro.auth import PisteAuthClient
from src.integrations.chorus_pro.exceptions import (
    ChorusProConfigurationError,
    ChorusProDepotError,
    ChorusProError,
)

# Le corps contient le PDF en base64 : timeout plus large que les clients
# sortants légers.
TIMEOUT_SECONDS = 30.0

# Endpoint de dépôt de flux facture (vérifié sur la sandbox : la variante
# ``transverses/v1/deposer/flux`` répond 403 sur ce périmètre).
DEPOSER_FLUX_PATH = "/cpro/factures/v1/deposer/flux"

# Syntaxe d'un dépôt Factur-X : flux mixte PDF/A-3 + XML CII.
SYNTAXE_FLUX_FACTURX = "IN_DP_E2_CII_FACTURX"


@dataclass(frozen=True)
class DepotFlux:
    """Résultat d'un dépôt de flux accepté par Chorus Pro."""

    numero_flux_depot: str
    date_depot: str
    syntaxe_flux: str


def is_chorus_configured() -> bool:
    """Vrai si les 4 credentials Chorus Pro / PISTE sont renseignés."""
    return bool(
        settings.CHORUS_PISTE_CLIENT_ID
        and settings.CHORUS_PISTE_CLIENT_SECRET
        and settings.CHORUS_TECH_LOGIN
        and settings.CHORUS_TECH_PASSWORD
    )


class ChorusProClient:
    """Appels à l'API Chorus Pro avec double authentification.

    Le paramètre ``transport`` (tests) est partagé avec le client OAuth
    interne : un même transport factice peut servir les deux URLs. Un
    ``PisteAuthClient`` peut aussi être fourni directement.
    """

    def __init__(
        self,
        auth: PisteAuthClient | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._auth = auth if auth is not None else PisteAuthClient(transport=transport)
        self._transport = transport

    async def deposer_flux_facturx(
        self, pdf_bytes: bytes, nom_fichier: str
    ) -> DepotFlux:
        """Dépose un fichier Factur-X (PDF/A-3 + XML CII) sur Chorus Pro.

        Le PDF part en base64 dans le body JSON. Lève ``ChorusProDepotError``
        si Chorus Pro rejette le dépôt (``codeRetour != 0``), ``ChorusProError``
        en cas d'échec technique (réseau, HTTP).
        """
        body = {
            "fichierFlux": base64.b64encode(pdf_bytes).decode("ascii"),
            "nomFichier": nom_fichier,
            "syntaxeFlux": SYNTAXE_FLUX_FACTURX,
            "avecSignature": False,
        }
        payload = await self._post(DEPOSER_FLUX_PATH, body)

        code_retour = payload.get("codeRetour")
        libelle = str(payload.get("libelle") or "aucun libellé fourni")
        if code_retour != 0:
            raise ChorusProDepotError(
                code_retour=code_retour if isinstance(code_retour, int) else -1,
                libelle=libelle,
            )

        numero_flux_depot = payload.get("numeroFluxDepot")
        if not isinstance(numero_flux_depot, str) or not numero_flux_depot:
            raise ChorusProError(
                "Réponse Chorus Pro sans numeroFluxDepot malgré un codeRetour à 0."
            )

        return DepotFlux(
            numero_flux_depot=numero_flux_depot,
            date_depot=str(payload.get("dateDepot") or ""),
            syntaxe_flux=str(payload.get("syntaxeFlux") or SYNTAXE_FLUX_FACTURX),
        )

    def _cpro_account_header(self) -> str:
        """Encode ``login:password`` du compte technique en base64."""
        login = settings.CHORUS_TECH_LOGIN
        password = settings.CHORUS_TECH_PASSWORD
        if not login or not password:
            raise ChorusProConfigurationError(
                "Compte technique Chorus Pro absent de la configuration "
                "(CHORUS_TECH_LOGIN / CHORUS_TECH_PASSWORD)."
            )
        return base64.b64encode(f"{login}:{password}".encode()).decode("ascii")

    async def _post(self, path: str, body: dict[str, object]) -> dict[str, object]:
        """POST authentifié vers Chorus Pro, avec un retry sur 401.

        Un 401 signifie un token révoqué avant son expiration théorique : le
        cache est invalidé et l'appel rejoué une seule fois avec un token neuf.
        """
        url = f"{settings.CHORUS_BASE_URL}{path}"
        token = await self._auth.get_token()

        for attempt in (1, 2):
            headers = {
                "Authorization": f"Bearer {token}",
                "cpro-account": self._cpro_account_header(),
            }
            try:
                async with httpx.AsyncClient(transport=self._transport) as client:
                    response = await client.post(
                        url, json=body, headers=headers, timeout=TIMEOUT_SECONDS
                    )
            except httpx.HTTPError as exc:
                # Le message httpx ne contient pas les headers : ni token ni
                # compte technique ne peuvent fuiter dans les logs.
                logger.error("Échec de l'appel Chorus Pro {} : {}", path, exc)
                raise ChorusProError(
                    "Chorus Pro est injoignable (réseau ou timeout)."
                ) from exc

            if response.status_code == 401 and attempt == 1:
                self._auth.invalidate()
                token = await self._auth.get_token()
                continue

            if response.status_code >= 400:
                logger.error(
                    "Chorus Pro a répondu HTTP {} sur {}", response.status_code, path
                )
                raise ChorusProError(
                    f"Chorus Pro a répondu HTTP {response.status_code}."
                )

            payload = response.json()
            if not isinstance(payload, dict):
                raise ChorusProError("Réponse Chorus Pro illisible (JSON attendu).")
            return payload

        raise AssertionError("inatteignable : la boucle retourne ou lève toujours")
