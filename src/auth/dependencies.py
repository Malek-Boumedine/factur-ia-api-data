from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.config import settings
from src.core.database import get_session
from src.utilisateurs.models import Utilisateur

# On définit l'URL de l'endpoint qui gérera le login
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/token")


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Utilisateur:
    """
    Récupère l'utilisateur actuel à partir du token JWT.
    Adapté pour l'asynchrone et SQLModel.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Impossible de valider les identifiants",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        # Décodage du token
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        email: str | None = payload.get("sub")
        if email is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception from None

    # requête asynchrone SQLModel
    statement = select(Utilisateur).where(Utilisateur.email == email)
    result = await session.exec(statement)
    user = result.first()

    if user is None:
        raise credentials_exception

    if not user.est_actif:
        raise HTTPException(status_code=400, detail="Utilisateur inactif")

    return user
