import asyncio
import logging
from importlib.metadata import PackageNotFoundError, version
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel.ext.asyncio.session import AsyncSession

from src.abonnements.router import router as abonnement_router
from src.administration.router import router as administration_router
from src.auth.router import router as auth_router
from src.catalogue_produits.router import router as catalogue_produits_router
from src.clients.router import router as clients_router
from src.core.config import settings
from src.core.database import get_session
from src.core.rate_limit import limiter
from src.core.telemetry import setup_telemetry
from src.documents.router import router as documents_router
from src.entreprises.router import router as entreprises_router
from src.factures.router import router as factures_router
from src.formes_juridiques.router import router as formes_juridiques_router
from src.taux_tva.router import router as taux_tva_router
from src.utilisateurs.plateforme_router import router as admins_plateforme_router
from src.utilisateurs.router import router as utilisateurs_router


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
        swagger_ui_parameters={"docExpansion": "none"},
    )

    # Rate-limiting (slowapi) : enregistre le limiteur et le handler dédié
    # renvoyant un 429 lorsque le quota est dépassé.
    _app.state.limiter = limiter
    _app.add_exception_handler(
        RateLimitExceeded,
        _rate_limit_exceeded_handler,  # type: ignore[arg-type]
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
    _app.include_router(utilisateurs_router)
    _app.include_router(admins_plateforme_router)
    _app.include_router(taux_tva_router)
    _app.include_router(formes_juridiques_router)
    _app.include_router(catalogue_produits_router)
    _app.include_router(factures_router)
    _app.include_router(documents_router)
    _app.include_router(entreprises_router)
    # Enregistré en dernier : les chemins du contrat OpenAPI suivent l'ordre
    # d'inclusion, et ajouter ce module en fin de liste garde les entrées
    # existantes à leur place (diff de `contracts/openapi.json` purement additif).
    _app.include_router(administration_router)

    # Tracing OpenTelemetry — no-op si OTEL_ENABLED est faux.
    setup_telemetry(_app)

    return _app


app = get_application()


logger = logging.getLogger(__name__)

# Délai maximal accordé au SELECT 1 de la sonde de readiness. Au-delà, la base
# est considérée indisponible : une sonde ne doit jamais pendre.
READY_DB_TIMEOUT_SECONDS = 2.0


@app.get("/health", tags=["Infrastructure"], include_in_schema=False)
async def health_check() -> dict[str, str]:
    """Sonde de liveness (Cloud Run startup/liveness).

    Répond 200 tant que le processus est vivant : aucune I/O, aucune
    dépendance externe. Un échec de cette sonde provoque un redémarrage du
    conteneur — elle ne doit donc jamais dépendre de la base de données.
    """
    return {
        "status": "ok",
        "app_name": settings.APP_NAME,
        "version": get_app_version(),
    }


@app.get("/ready", tags=["Infrastructure"], include_in_schema=False)
async def readiness_check(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, str]:
    """Sonde de readiness : le service peut-il traiter des requêtes ?

    Vérifie la seule dépendance critique (MySQL) via un SELECT 1 borné dans
    le temps. Répond 503 si la base est indisponible : l'orchestrateur retire
    alors le conteneur du trafic sans le redémarrer. Le détail de l'erreur
    part dans les logs, jamais dans la réponse.
    """
    try:
        await asyncio.wait_for(
            session.execute(text("SELECT 1")), timeout=READY_DB_TIMEOUT_SECONDS
        )
    except (TimeoutError, SQLAlchemyError, OSError) as exc:
        logger.warning("Sonde de readiness : base indisponible (%s)", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="service non prêt",
        ) from exc
    return {"status": "ready"}


@app.get("/", tags=["Infrastructure"])
async def root() -> dict[str, str]:
    """Accueil de l'API."""
    return {"message": f"Welcome to {settings.APP_NAME} API"}


print(get_app_version())
