from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.abonnements.models import UtilisateurAbonnement
from src.auth.dependencies import (
    RequirePermission,
    get_current_user,
    verify_tenant_access,
)
from src.core.database import get_session
from src.core.security import get_password_hash
from src.utilisateurs.models import Utilisateur
from src.utilisateurs.schemas import (
    UtilisateurCreate,
    UtilisateurRead,
    UtilisateurUpdate,
)

router = APIRouter(prefix="/utilisateurs", tags=["Gestion des Utilisateurs"])


@router.get("/me", response_model=UtilisateurRead)
async def get_my_profile(
    current_user: Annotated[Utilisateur, Depends(get_current_user)],
) -> Any:
    """
    Récupère le profil de l'utilisateur actuellement connecté.
    """
    return current_user


@router.patch("/me", response_model=UtilisateurRead)
async def update_my_profile(
    user_in: UtilisateurUpdate,
    current_user: Annotated[Utilisateur, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Any:
    """
    Permet à l'utilisateur de modifier ses propres informations.
    """
    user_data = user_in.model_dump(exclude_unset=True)
    for key, value in user_data.items():
        setattr(current_user, key, value)

    session.add(current_user)
    await session.commit()
    await session.refresh(current_user)
    return current_user


@router.get("/", response_model=list[UtilisateurRead])
async def list_team_members(
    abonnement_id: Annotated[int, Depends(verify_tenant_access)],
    _: Annotated[Utilisateur, Depends(RequirePermission("user:read"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Any:
    """
    Liste tous les utilisateurs rattachés à l'abonnement actif (l'équipe).
    """
    # On joint la table utilisateur avec la table de liaison utilisateur_abonnement
    statement = (
        select(Utilisateur)
        .join(UtilisateurAbonnement)
        .where(UtilisateurAbonnement.id_abonnement == abonnement_id)
    )
    result = await session.exec(statement)
    return result.all()


@router.post("/", response_model=UtilisateurRead, status_code=status.HTTP_201_CREATED)
async def create_team_member(
    user_in: UtilisateurCreate,
    abonnement_id: Annotated[int, Depends(verify_tenant_access)],
    _: Annotated[Utilisateur, Depends(RequirePermission("user:create"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Any:
    """
    Crée un nouvel utilisateur et le rattache automatiquement à l'abonnement actuel.
    """
    # 1. Vérifier si l'email existe déjà
    statement = select(Utilisateur).where(Utilisateur.email == user_in.email)
    existing_user = await session.exec(statement)
    if existing_user.first():
        raise HTTPException(status_code=400, detail="Cet email est déjà utilisé")

    # 2. Créer l'utilisateur avec le mot de passe haché
    user_data = user_in.model_dump(exclude={"password"})
    db_user = Utilisateur(
        **user_data, hash_mot_de_passe=get_password_hash(user_in.password)
    )
    session.add(db_user)
    await session.flush()  # Pour récupérer l'ID sans commiter tout de suite

    # 3. Créer la liaison avec l'abonnement actuel
    link = UtilisateurAbonnement(
        id_utilisateur=db_user.id,
        id_abonnement=abonnement_id,
        est_admin_abonnement=False,
    )
    session.add(link)

    await session.commit()
    await session.refresh(db_user)
    return db_user


@router.post(
    "/inscription", response_model=UtilisateurRead, status_code=status.HTTP_201_CREATED
)
async def register_public_user(
    user_in: UtilisateurCreate, session: Annotated[AsyncSession, Depends(get_session)]
) -> Any:
    """
    Inscription publique d'un nouvel utilisateur.
    Aucun abonnement ni authentification requis au départ.
    """
    # 1. Vérifier si l'email existe déjà
    statement = select(Utilisateur).where(Utilisateur.email == user_in.email)
    existing_user = await session.exec(statement)
    if existing_user.first():
        raise HTTPException(status_code=400, detail="Cet email est déjà utilisé")

    # 2. Créer l'utilisateur avec le mot de passe haché
    user_data = user_in.model_dump(exclude={"password"})
    db_user = Utilisateur(
        **user_data, hash_mot_de_passe=get_password_hash(user_in.password)
    )
    session.add(db_user)

    # 3. On sauvegarde directement (pas de liaison UtilisateurAbonnement)
    await session.commit()
    await session.refresh(db_user)
    return db_user
