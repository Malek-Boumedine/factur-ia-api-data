"""
Logique métier de gestion des administrateurs de plateforme.

Concentre les garde-fous de sécurité (auto-révocation interdite, compte
protégé, dernier admin) hors du router, qui reste mince. Toutes ces opérations
n'agissent que sur le flag `admin_plateforme` : elles ne touchent jamais aux
rôles métier ni aux rattachements d'entreprise.
"""

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.auth.service import invalidate_pending_reset_tokens
from src.core.db_errors import UniqueConflict, conflict_from_integrity_error
from src.core.security import get_password_hash, verify_password
from src.utilisateurs.models import Utilisateur

# Contrainte unique de la table `utilisateur` mappée vers un message clair.
_UTILISATEUR_EMAIL_CONFLICTS = [
    UniqueConflict("email", "Cet email est déjà utilisé."),
]


async def list_platform_admins(session: AsyncSession) -> list[Utilisateur]:
    """Renvoie tous les administrateurs de la plateforme."""
    statement = select(Utilisateur).where(Utilisateur.admin_plateforme == True)  # noqa: E712
    result = await session.exec(statement)
    return list(result.all())


async def search_users_by_email(
    session: AsyncSession, email: str, limit: int = 20
) -> list[Utilisateur]:
    """
    Recherche des utilisateurs par email (partielle, insensible à la casse).

    Privilège élevé réservé aux admins plateforme : permet de retrouver un
    utilisateur global (au-delà d'une entreprise) pour le désigner à la
    promotion. Requête paramétrée, résultats plafonnés à `limit`.
    """
    statement = (
        select(Utilisateur)
        .where(Utilisateur.email.ilike(f"%{email}%"))  # type: ignore[attr-defined]
        .order_by(Utilisateur.email)
        .limit(limit)
    )
    result = await session.exec(statement)
    return list(result.all())


async def change_password(
    session: AsyncSession,
    current_user: Utilisateur,
    mot_de_passe_actuel: str,
    nouveau_mot_de_passe: str,
) -> None:
    """
    Change le mot de passe d'un utilisateur déjà authentifié.

    Sécurité : re-vérifie d'abord le mot de passe actuel — on ne change jamais
    un mot de passe à l'aveugle sur une session ouverte. Refuse un nouveau mot
    de passe identique à l'ancien. En cas d'erreur, renvoie un 400 (et non 401)
    pour ne pas déclencher côté front la logique de session expirée.

    Après application du nouveau hash, invalide les liens de réinitialisation en
    cours (cohérence avec le flux « mot de passe oublié » : un lien émis avant
    ne doit plus être exploitable), puis valide la transaction.
    """
    if not verify_password(mot_de_passe_actuel, current_user.hash_mot_de_passe):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le mot de passe actuel est incorrect.",
        )

    if verify_password(nouveau_mot_de_passe, current_user.hash_mot_de_passe):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le nouveau mot de passe doit être différent de l'actuel.",
        )

    # Un utilisateur authentifié possède toujours un identifiant persisté.
    if current_user.id is None:
        raise HTTPException(status_code=500, detail="ID utilisateur manquant")

    current_user.hash_mot_de_passe = get_password_hash(nouveau_mot_de_passe)
    session.add(current_user)
    await invalidate_pending_reset_tokens(session, current_user.id)
    await session.commit()


async def change_email(
    session: AsyncSession,
    current_user: Utilisateur,
    mot_de_passe_actuel: str,
    nouvel_email: str,
) -> None:
    """
    Change l'email (identifiant de connexion) d'un utilisateur authentifié.

    Sécurité : re-vérifie d'abord le mot de passe actuel — on ne change jamais
    l'identifiant de connexion à l'aveugle sur une session ouverte. En cas
    d'échec, renvoie un 400 (et non 401), cohérent avec le changement de mot de
    passe et sans déclencher côté front la logique de session expirée.

    Refuse un email identique à l'actuel (400) et gère l'unicité : un email déjà
    utilisé par un autre compte renvoie un 409 (pré-vérification déterministe +
    filet `IntegrityError` contre la course), jamais un 500.
    """
    if not verify_password(mot_de_passe_actuel, current_user.hash_mot_de_passe):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le mot de passe actuel est incorrect.",
        )

    if nouvel_email == current_user.email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le nouvel email doit être différent de l'actuel.",
        )

    # Pré-vérification déterministe : l'email diffère de l'actuel, donc toute
    # ligne trouvée appartient à un autre compte.
    existing = await session.exec(
        select(Utilisateur).where(Utilisateur.email == nouvel_email)
    )
    if existing.first() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cet email est déjà utilisé.",
        )

    current_user.email = nouvel_email
    session.add(current_user)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise conflict_from_integrity_error(exc, _UTILISATEUR_EMAIL_CONFLICTS) from None


async def _get_user_or_404(session: AsyncSession, utilisateur_id: int) -> Utilisateur:
    """Charge un utilisateur par son ID ou lève une 404."""
    user = await session.get(Utilisateur, utilisateur_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Utilisateur introuvable."
        )
    return user


async def promote_platform_admin(
    session: AsyncSession, utilisateur_id: int
) -> Utilisateur:
    """
    Promeut un utilisateur au rang d'administrateur de plateforme.

    Idempotent : promouvoir un admin déjà en place ne fait rien. Seul le flag
    `admin_plateforme` est modifié.
    """
    user = await _get_user_or_404(session, utilisateur_id)

    if not user.admin_plateforme:
        user.admin_plateforme = True
        session.add(user)
        await session.commit()
        await session.refresh(user)

    return user


async def revoke_platform_admin(
    session: AsyncSession, utilisateur_id: int, current_user: Utilisateur
) -> Utilisateur:
    """
    Révoque le statut d'administrateur de plateforme d'un utilisateur.

    Garde-fous : un admin ne peut pas se révoquer lui-même, un compte protégé
    est intouchable, et le dernier admin ne peut pas être révoqué (il en faut
    toujours au moins un). Seul le flag `admin_plateforme` est modifié.
    """
    user = await _get_user_or_404(session, utilisateur_id)

    if user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Vous ne pouvez pas révoquer votre propre statut d'administrateur.",
        )

    if user.compte_protege:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Ce compte est protégé et ne peut pas être révoqué.",
        )

    if not user.admin_plateforme:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cet utilisateur n'est pas administrateur de la plateforme.",
        )

    total_admins = (
        await session.exec(
            select(func.count()).select_from(
                select(Utilisateur)
                .where(Utilisateur.admin_plateforme == True)  # noqa: E712
                .subquery()
            )
        )
    ).one()
    if total_admins <= 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Impossible de révoquer le dernier administrateur de la plateforme.",
        )

    user.admin_plateforme = False
    session.add(user)
    await session.commit()
    await session.refresh(user)

    return user
