from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.database import get_session
from src.core.security import create_access_token, verify_password
from src.utilisateurs.models import Utilisateur

router = APIRouter(prefix="/auth", tags=["Authentification"])


@router.post("/token", operation_id="login")
async def login_for_access_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, str]:
    """
    Authentifie un utilisateur et retourne un token JWT.
    OAuth2PasswordRequestForm attend 'username' (ici l'email) et 'password'.
    """
    # recherche de l'utilisateur par email
    statement = select(Utilisateur).where(Utilisateur.email == form_data.username)
    result = await session.exec(statement)
    user = result.first()

    # vérification de l'existence et du mot de passe
    if not user or not verify_password(form_data.password, user.hash_mot_de_passe):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email ou mot de passe incorrect",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # génération du token
    # On met l'email dans le 'sub' du token
    access_token = create_access_token(data={"sub": user.email})

    return {"access_token": access_token, "token_type": "bearer"}
