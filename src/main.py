from importlib.metadata import PackageNotFoundError, version

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.abonnements.router import router as abonnement_router
from src.auth.router import router as auth_router
from src.clients.router import router as clients_router
from src.core.config import settings


def get_app_version() -> str:
    try:
        # nom défini dans le [project] name du pyproject.toml
        return version("factur-ia-api-data")
    except PackageNotFoundError:
        # version de secours si le package n'est pas installé
        return "0.1.0-dev"


def get_application() -> FastAPI:
    """
    Initialise et configure l'instance FastAPI.
    Utilise la configuration technique (anglais) pour l'infrastructure.
    """

    _app = FastAPI(
        title=settings.APP_NAME,
        debug=settings.DEBUG,
        version=get_app_version(),
    )

    # Configuration du CORS
    # On autorise tout en développement. À restreindre en production.
    _app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    _app.include_router(auth_router)
    _app.include_router(clients_router)
    _app.include_router(abonnement_router)

    return _app


app = get_application()


@app.get("/health", tags=["Infrastructure"])
async def health_check() -> dict[str, str]:
    """Endpoint technique pour vérifier l'état de l'API."""
    return {
        "status": "healthy",
        "app_name": settings.APP_NAME,
        "environment": settings.ENVIRONNEMENT,
    }


@app.get("/", tags=["Infrastructure"])
async def root() -> dict[str, str]:
    """Accueil de l'API."""
    return {"message": f"Welcome to {settings.APP_NAME} API"}


print(get_app_version())
