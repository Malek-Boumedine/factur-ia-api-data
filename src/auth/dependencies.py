from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.auth.models import Permission, PermissionRole, Role, UtilisateurRole
from src.core.config import settings
from src.core.database import get_session
from src.entreprises.models import Entreprise, UtilisateurEntreprise
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


# Message renvoyé lorsque l'entreprise a été suspendue par la plateforme. Il est
# volontairement explicite : le client web s'en sert pour afficher un écran
# « compte suspendu » plutôt qu'une erreur d'accès générique.
ENTREPRISE_SUSPENDUE_DETAIL = (
    "Cette entreprise a été suspendue par l'administration de la plateforme. "
    "Contactez le support."
)


async def _resolve_membership(
    session: AsyncSession, utilisateur_id: int | None, entreprise_id: int
) -> tuple[UtilisateurEntreprise, Entreprise]:
    """
    Résout l'appartenance d'un utilisateur à une entreprise et l'état de
    celle-ci, en une seule requête (jointure pivot -> entreprise).

    Socle commun de ``verify_tenant_access`` et ``require_entreprise_admin``,
    pour que le contrôle de suspension s'applique identiquement aux deux : sans
    cela, un administrateur d'entreprise pourrait continuer d'agir (changer de
    plan, par exemple) sur une entreprise suspendue.

    Renvoie 403 si l'utilisateur n'est pas membre, et 403 également si
    l'entreprise est suspendue — deux messages distincts, aucun des deux ne
    révélant d'information sur une entreprise dont l'utilisateur n'est pas
    membre.
    """
    statement = (
        select(UtilisateurEntreprise, Entreprise)
        .join(Entreprise, col(Entreprise.id) == UtilisateurEntreprise.id_entreprise)
        .where(UtilisateurEntreprise.id_utilisateur == utilisateur_id)
        .where(UtilisateurEntreprise.id_entreprise == entreprise_id)
    )

    result = await session.exec(statement)
    row = result.first()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès refusé. Vous n'appartenez pas à cette entreprise.",
        )

    lien_entreprise, entreprise = row

    if not entreprise.est_actif:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ENTREPRISE_SUSPENDUE_DETAIL,
        )

    return lien_entreprise, entreprise


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

    Refuse également l'accès (403) si l'entreprise a été suspendue par un
    administrateur de plateforme : le blocage est total sur toutes les routes
    tenant. Les routes hors tenant (`/utilisateurs/me`, `/abonnements/me`)
    continuent de répondre, afin que le client puisse expliquer la situation.
    """
    await _resolve_membership(session, current_user.id, x_entreprise_id)
    return x_entreprise_id


async def require_entreprise_admin(
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
    Garde-fou pour les actions sensibles au niveau d'une entreprise (tenant).

    Reprend le contrôle d'appartenance et de suspension de
    ``verify_tenant_access`` et exige en plus le flag ``est_admin`` : seul un
    administrateur de l'entreprise active peut poursuivre. Renvoie 403 si
    l'utilisateur n'appartient pas à l'entreprise, si celle-ci est suspendue, ou
    s'il en est un membre non-admin. Réutilisable pour d'autres opérations
    d'administration métier.
    """
    lien_entreprise, _ = await _resolve_membership(
        session, current_user.id, x_entreprise_id
    )

    if not lien_entreprise.est_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Action réservée aux administrateurs de l'entreprise.",
        )

    return x_entreprise_id


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
        entreprise_id: Annotated[int, Depends(verify_tenant_access)],
        session: Annotated[AsyncSession, Depends(get_session)],
    ) -> Utilisateur:
        """
        Exécute la vérification des droits d'accès lors de l'appel de l'endpoint.

        La permission est évaluée **dans le contexte de l'entreprise active**
        (`x-entreprise-id`, validée par ``verify_tenant_access``) : seuls les rôles
        rattachés à cette entreprise — ou les rôles globaux (``id_entreprise`` NULL)
        — sont pris en compte. Un rôle élevé détenu dans une autre entreprise ne
        confère donc aucun droit ici (isolation RBAC par tenant).
        """
        statement = (
            select(Permission)
            .join(PermissionRole, Permission.id == PermissionRole.id_permission)  # type: ignore
            .join(Role, Role.id == PermissionRole.id_role)  # type: ignore
            .join(UtilisateurRole, Role.id == UtilisateurRole.id_role)  # type: ignore
            .where(UtilisateurRole.id_utilisateur == current_user.id)
            .where(
                (UtilisateurRole.id_entreprise == entreprise_id)
                | (UtilisateurRole.id_entreprise.is_(None))  # type: ignore[union-attr]
            )
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


async def require_admin_plateforme(
    current_user: Annotated[Utilisateur, Depends(get_current_user)],
) -> Utilisateur:
    """
    Dépendance de sécurité au niveau plateforme.

    Autorise uniquement les administrateurs de la plateforme (flag
    `admin_plateforme` sur l'utilisateur du JWT). Contrairement à
    `verify_tenant_access`, elle est indépendante du header `x-entreprise-id` :
    l'admin plateforme agit au niveau global, hors périmètre d'une entreprise.
    """
    if not current_user.admin_plateforme:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès réservé aux administrateurs de la plateforme.",
        )
    return current_user
