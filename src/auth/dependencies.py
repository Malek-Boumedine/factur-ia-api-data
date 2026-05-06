from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.auth.models import Permission, PermissionRole, Role, UtilisateurRole
from src.core.config import settings
from src.core.database import get_session
from src.entreprises.models import UtilisateurEntreprise
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


# gestion RBAC
class RequirePermission:
    """
    Dépendance FastAPI pour le contrôle des accès basé sur les rôles (RBAC).

    Cette classe est conçue pour être injectée dans les routes FastAPI via `Depends()`.
    Elle vérifie de manière asynchrone en base de données si l'utilisateur
    authentifié possède la permission spécifique requise pour exécuter l'action.
    """

    def __init__(self, required_permission: str) -> None:
        self.required_permission = required_permission

    async def __call__(
        self,
        current_user: Annotated[Utilisateur, Depends(get_current_user)],
        session: Annotated[AsyncSession, Depends(get_session)],
    ) -> Utilisateur:
        """
        Exécute la vérification des droits d'accès lors de l'appel de l'endpoint.
        """
        statement = (
            select(Permission)
            .join(PermissionRole, Permission.id == PermissionRole.id_permission)  # type: ignore
            .join(Role, Role.id == PermissionRole.id_role)  # type: ignore
            .join(UtilisateurRole, Role.id == UtilisateurRole.id_role)  # type: ignore
            .where(UtilisateurRole.id_utilisateur == current_user.id)
            .where(Permission.libelle == self.required_permission)
        )

        result = await session.exec(statement)
        has_permission = result.first()

        if not has_permission:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Privilèges insuffisants. \
                    Permission requise : {self.required_permission}",
            )

        return current_user


# isolation de l'entreprise (tenant)
async def verify_tenant_access(
    x_entreprise_id: Annotated[
        int,
        Header(
            title="ID de l'entreprise",
            description="Identifiant de l'entreprise (tenant) \
                actif transmis dans les en-têtes.",
        ),
    ],
    current_user: Annotated[Utilisateur, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> int:
    """
    Dépendance d'isolation des données (Tenant Isolation / Multitenancy).

    Intercepte le header HTTP `X-Entreprise-ID` envoyé par le client et vérifie
    en base de données si l'utilisateur authentifié est légitimement rattaché
    à cet espace de travail.
    """
    statement = (
        select(UtilisateurEntreprise)
        .where(UtilisateurEntreprise.id_utilisateur == current_user.id)
        .where(UtilisateurEntreprise.id_entreprise == x_entreprise_id)
    )

    result = await session.exec(statement)
    lien_entreprise = result.first()

    if not lien_entreprise:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès refusé. Vous n'appartenez pas à cette entreprise.",
        )

    return x_entreprise_id
