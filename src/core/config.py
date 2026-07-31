from typing import Any

from cryptography.fernet import Fernet
from pydantic import field_validator, model_validator
from pydantic_core import PydanticUndefined
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # global
    APP_NAME: str
    ENVIRONNEMENT: str
    DEBUG: bool

    # bdd
    DB_HOST: str
    DB_PORT: int
    DB_NAME: str
    DB_USER: str
    DB_PASSWORD: str
    DB_CHARSET: str

    # API
    API_PORT: int
    API_HOST: str

    # SECURITY
    ACCESS_TOKEN_EXPIRE_MINUTES: int
    ALGORITHM: str
    SECRET_KEY: str

    SECRET_OCR_TOKEN: str

    # Chiffrement des IBAN au repos (Fernet). Requise sans défaut : sans clé,
    # l'application ne démarre pas — jamais de repli en stockage clair.
    # ATTENTION : perdre cette clé rend les IBAN chiffrés irrécupérables.
    IBAN_ENCRYPTION_KEY: str

    # API IA D'EXTRACTION (OCR)
    IA_API_BASE_URL: str

    # CHORUS PRO (via PISTE) — environnement de QUALIFICATION (sandbox).
    # Optionnels : si les credentials sont absents, l'application démarre
    # normalement et la route de transmission répond 503. Le passage en
    # production se fait uniquement par l'environnement : surcharger les
    # deux URLs (oauth.piste.gouv.fr / api.piste.gouv.fr) et les 4
    # credentials de production, aucun changement de code.
    CHORUS_PISTE_CLIENT_ID: str | None = None
    CHORUS_PISTE_CLIENT_SECRET: str | None = None
    CHORUS_TECH_LOGIN: str | None = None
    CHORUS_TECH_PASSWORD: str | None = None
    CHORUS_OAUTH_URL: str = "https://sandbox-oauth.piste.gouv.fr/api/oauth/token"
    CHORUS_BASE_URL: str = "https://sandbox-api.piste.gouv.fr"

    # RÉINITIALISATION DE MOT DE PASSE
    # Valeurs par défaut fournies pour ne pas bloquer le démarrage ;
    # à surcharger via l'environnement en production.
    RESET_TOKEN_EXPIRE_HOURS: int = 2
    FRONTEND_RESET_URL: str = "http://localhost:8000/reinitialiser-mot-de-passe"
    EMAIL_SENDER: str = "no-reply@factur-ia.local"

    # ADMIN PLATEFORME (seed du compte racine)
    # Optionnels : si l'un des deux est absent, le seed de l'admin est ignoré
    # (avec un avertissement) sans bloquer le démarrage.
    PLATFORM_ADMIN_EMAIL: str | None = None
    PLATFORM_ADMIN_PASSWORD: str | None = None
    PLATFORM_ADMIN_NOM: str = "Admin"
    PLATFORM_ADMIN_PRENOM: str = "Plateforme"

    @field_validator("IBAN_ENCRYPTION_KEY")
    @classmethod
    def _validate_fernet_key(cls, value: str) -> str:
        """Refuse au démarrage une clé mal formée, avec la marche à suivre."""
        try:
            Fernet(value.encode())
        except (ValueError, TypeError) as exc:
            raise ValueError(
                "IBAN_ENCRYPTION_KEY n'est pas une clé Fernet valide. "
                "Générer une clé avec : uv run python -c "
                '"from cryptography.fernet import Fernet; '
                'print(Fernet.generate_key().decode())"'
            ) from exc
        return value

    @model_validator(mode="before")
    @classmethod
    def _blank_env_to_default(cls, data: Any) -> Any:
        """
        Traite une variable d'environnement vide (`FOO=`) comme non définie.

        Sans cela, une chaîne vide dans le `.env` écrase la valeur par défaut
        du champ et casse le parsing (ex : un `int` attendu reçoit `''`). On
        retire donc les clés vides des champs qui possèdent un défaut, pour
        que ce défaut s'applique. Les champs requis restent obligatoires.
        """
        if isinstance(data, dict):
            for name, field in cls.model_fields.items():
                has_default = (
                    field.default is not PydanticUndefined
                    or field.default_factory is not None
                )
                if has_default and data.get(name) == "":
                    del data[name]
        return data

    @property
    def DATABASE_URL(self) -> str:
        """
        Construit l'URL MySQL asynchrone dynamiquement.
        On utilise mysql+aiomysql pour le driver asynchrone
        """
        return (
            f"mysql+aiomysql://{self.DB_USER}:{self.DB_PASSWORD}@"
            f"{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
            f"?charset={self.DB_CHARSET}"
        )

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )


settings = Settings()
