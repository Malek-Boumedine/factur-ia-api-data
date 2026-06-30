from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.auth.dependencies import get_current_user
from src.auth.models import Role
from src.auth.schemas import RoleRead
from src.core.database import get_session
from src.core.security import create_access_token, verify_password
from src.entreprises.models import UtilisateurEntreprise
from src.utilisateurs.models import Utilisateur

router = APIRouter(prefix="/auth", tags=["Authentification"])


@router.post("/token", operation_id="login")
async def login_for_access_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, Any]:
    """
    Authentifie un utilisateur et retourne un token JWT.

    L'authentification s'effectue au niveau global de l'utilisateur (email).
    Une fois authentifié, l'utilisateur devra fournir un header 'x-entreprise-id'
    sur les routes métiers pour interagir avec les données de ses entreprises.
    """
    statement = select(Utilisateur).where(Utilisateur.email == form_data.username)
    result = await session.exec(statement)
    user = result.first()

    if not user or not verify_password(form_data.password, user.hash_mot_de_passe):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email ou mot de passe incorrect",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(data={"sub": user.email})

    statement_entreprise = select(UtilisateurEntreprise).where(
        UtilisateurEntreprise.id_utilisateur == user.id
    )
    result_entreprise = await session.exec(statement_entreprise)
    lien_entreprise = result_entreprise.first()
    entreprise_id = lien_entreprise.id_entreprise if lien_entreprise else None

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "entreprise_id": entreprise_id,
    }


@router.get("/roles", response_model=list[RoleRead])
async def list_roles(
    _: Annotated[Utilisateur, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Any:
    """
    Retourne la liste des rôles disponibles.
    Accessible à tout utilisateur authentifié.
    """
    result = await session.exec(select(Role))
    return result.all()
