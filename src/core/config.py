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
