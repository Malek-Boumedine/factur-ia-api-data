from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.config import settings

# 1. création du moteur asynchrone (Engine)
# 'echo' permet de voir les requêtes SQL générées dans la console en mode DEBUG
engine = create_async_engine(settings.DATABASE_URL, echo=settings.DEBUG, future=True)

# 2. création de la fabrique de sessions (SessionLocal)
async_session_maker = async_sessionmaker(
    bind=engine, class_=AsyncSession, expire_on_commit=False
)


# 3. dépendance (Dependency Injection) pour FastAPI
async def get_session() -> AsyncGenerator[AsyncSession]:
    """
    Générateur de session de base de données.
    à utiliser avec Depends(get_session) dans les routes.
    """
    async with async_session_maker() as session:
        yield session


print(settings)
