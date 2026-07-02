from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.auth.dependencies import get_current_user
from src.auth.models import Role
from src.auth.schemas import (
    MessageResponse,
    MotDePasseOublieRequest,
    ReinitialisationRequest,
    RoleRead,
)
from src.auth.service import apply_password_reset, request_password_reset
from src.core.database import get_session
from src.core.rate_limit import limiter
from src.core.security import create_access_token, verify_password
from src.entreprises.models import UtilisateurEntreprise
from src.integrations.email.service import EmailSender, get_email_sender
from src.utilisateurs.models import Utilisateur

router = APIRouter(prefix="/auth", tags=["Authentification"])

# Message neutre renvoyé quel que soit l'état du compte : ne divulgue jamais
# l'existence (ou non) d'un email en base.
_NEUTRAL_MESSAGE = (
    "Si un compte est associé à cet email, un lien de réinitialisation vient "
    "d'être envoyé."
)


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


@router.post(
    "/mot-de-passe-oublie",
    response_model=MessageResponse,
    operation_id="forgot_password",
)
@limiter.limit("5/hour")
async def forgot_password(
    request: Request,
    payload: MotDePasseOublieRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    email_sender: Annotated[EmailSender, Depends(get_email_sender)],
) -> MessageResponse:
    """
    Déclenche l'envoi d'un lien de réinitialisation de mot de passe.

    La réponse est **toujours identique**, que l'email corresponde à un compte
    ou non, afin de ne pas divulguer l'existence d'un utilisateur.
    """
    await request_password_reset(session, payload.email, email_sender)
    return MessageResponse(message=_NEUTRAL_MESSAGE)


@router.post(
    "/reinitialiser-mot-de-passe",
    response_model=MessageResponse,
    operation_id="reset_password",
)
@limiter.limit("10/hour")
async def reset_password(
    request: Request,
    payload: ReinitialisationRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MessageResponse:
    """
    Réinitialise le mot de passe à partir d'un token reçu par email.

    Le token doit exister, être non expiré et ne pas avoir déjà servi. En cas
    d'échec, un message générique est renvoyé (pas de détail sur la cause).
    """
    success = await apply_password_reset(
        session, payload.token, payload.nouveau_mot_de_passe
    )
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Lien de réinitialisation invalide ou expiré.",
        )
    return MessageResponse(message="Votre mot de passe a été réinitialisé.")


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
