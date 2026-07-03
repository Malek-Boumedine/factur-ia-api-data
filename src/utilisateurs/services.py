"""
Logique métier de gestion des administrateurs de plateforme.

Concentre les garde-fous de sécurité (auto-révocation interdite, compte
protégé, dernier admin) hors du router, qui reste mince. Toutes ces opérations
n'agissent que sur le flag `admin_plateforme` : elles ne touchent jamais aux
rôles métier ni aux rattachements d'entreprise.
"""

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.utilisateurs.models import Utilisateur


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
