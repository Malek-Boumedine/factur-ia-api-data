"""Chiffrement au repos et masquage de l'IBAN.

Limite de sécurité, à connaître : Fernet (clé symétrique en variable
d'environnement ``IBAN_ENCRYPTION_KEY``) protège contre une fuite de la base
(dump SQL, sauvegarde volée) — sans la clé, les IBAN sont illisibles. Il ne
protège PAS contre une compromission du serveur applicatif, où la clé et le
code de déchiffrement résident. L'étape suivante (hors MVP) est une clé
externalisée (KMS).

Perdre la clé rend les IBAN chiffrés définitivement irrécupérables : elle se
sauvegarde au même titre que les credentials de la base.

Convention : ne jamais logger ``facture.iban`` ni le payload OCR brut.
"""

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import Dialect, String
from sqlalchemy.types import TypeDecorator

# Tout token Fernet (version 0x80 + timestamp) commence par ce préfixe en
# base64url : il distingue une valeur chiffrée d'un clair hérité (un IBAN,
# en majuscules et chiffres, ne peut pas commencer par « gAAAA »).
FERNET_TOKEN_PREFIX = "gAAAA"  # noqa: S105 — préfixe public du format, pas un secret

# Caractère utilisé pour masquer l'IBAN dans les réponses API : sa présence
# dans une valeur entrante signale un masque renvoyé par erreur par le front.
MASK_CHAR = "•"


class DechiffrementError(RuntimeError):
    """Valeur en base indéchiffrable : clé erronée ou donnée corrompue."""


@lru_cache
def _get_fernet() -> Fernet:
    """Instance Fernet construite depuis les settings (clé validée au boot).

    Import paresseux : le module doit rester importable (migrations, tests
    unitaires du masquage) sans déclencher la validation complète des settings.
    """
    from src.core.config import settings

    return Fernet(settings.IBAN_ENCRYPTION_KEY.encode())


def encrypt_value(value: str) -> str:
    """Chiffre une valeur en clair vers un token Fernet (base64url)."""
    token: bytes = _get_fernet().encrypt(value.encode())
    return token.decode()


def decrypt_value(value: str) -> str:
    """Déchiffre un token Fernet ; erreur explicite si la clé ne correspond pas."""
    try:
        clair: bytes = _get_fernet().decrypt(value.encode())
        return clair.decode()
    except InvalidToken as exc:
        raise DechiffrementError(
            "Impossible de déchiffrer la valeur stockée : la clé "
            "IBAN_ENCRYPTION_KEY ne correspond pas à celle utilisée au "
            "chiffrement, ou la donnée est corrompue."
        ) from exc


class EncryptedStr(TypeDecorator[str]):
    """Colonne chiffrée au repos : clair côté Python, token Fernet en base.

    Le chiffrement est transparent pour les modèles et services ; seule une
    lecture SQL brute (ou un dump) voit le token. Jamais de repli en clair :
    sans clé valide, l'application ne démarre pas (validation des settings).
    """

    # Un IBAN (34 caractères max) chiffré Fernet fait ~140 caractères en
    # base64url (25 octets d'en-tête + 48 de ciphertext + 32 de HMAC).
    impl = String(255)
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect: Dialect) -> str | None:
        if value is None:
            return None
        return encrypt_value(value)

    def process_result_value(self, value: str | None, dialect: Dialect) -> str | None:
        if value is None:
            return None
        return decrypt_value(value)


def is_masked(value: str) -> bool:
    """Vrai si la valeur est un IBAN masqué renvoyé tel quel par un client."""
    return MASK_CHAR in value


def mask_iban(iban: str) -> str:
    """Masque un IBAN pour l'affichage : ``FR76 •••• •••• •••• •••• •••0 189``.

    Au plus 8 caractères réels restent visibles : les 4 premiers (code pays et
    clé de contrôle, non sensibles) et les 4 derniers. Le résultat est groupé
    par blocs de 4 séparés par des espaces, quel que soit le format d'entrée.
    """
    compact = iban.replace(" ", "")
    n = len(compact)
    if n <= 4:
        masked = MASK_CHAR * n
    elif n <= 8:
        masked = MASK_CHAR * (n - 4) + compact[-4:]
    else:
        masked = compact[:4] + MASK_CHAR * (n - 8) + compact[-4:]
    return " ".join(masked[i : i + 4] for i in range(0, len(masked), 4))
