from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.auth.dependencies import (
    RequirePermission,
    get_current_user,
    verify_tenant_access,
)
from src.core.database import get_session
from src.core.security import get_password_hash
from src.entreprises.models import UtilisateurEntreprise
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
    Permet à l'utilisateur de modifier ses propres informations personnelles.
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
    entreprise_id: Annotated[int, Depends(verify_tenant_access)],
    _: Annotated[Utilisateur, Depends(RequirePermission("users:read"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Any:
    """
    Liste tous les utilisateurs rattachés à l'entreprise active (l'équipe).
    """
    # joint utilisateur avec table pivot UtilisateurEntreprise
    # pour filtrer par entreprise
    statement = (
        select(Utilisateur)
        .join(UtilisateurEntreprise)
        .where(UtilisateurEntreprise.id_entreprise == entreprise_id)
    )
    result = await session.exec(statement)
    return result.all()


@router.post("/", response_model=UtilisateurRead, status_code=status.HTTP_201_CREATED)
async def create_team_member(
    user_in: UtilisateurCreate,
    entreprise_id: Annotated[int, Depends(verify_tenant_access)],
    _: Annotated[Utilisateur, Depends(RequirePermission("user:create"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Any:
    """
    Crée un nouvel utilisateur et le rattache automatiquement à l'entreprise actuelle.
    """
    # 1. Vérifier si l'email existe déjà globalement
    statement = select(Utilisateur).where(Utilisateur.email == user_in.email)
    existing_user_result = await session.exec(statement)
    if existing_user_result.first():
        raise HTTPException(status_code=400, detail="Cet email est déjà utilisé")

    # 2. Créer l'utilisateur avec le mot de passe haché
    user_data = user_in.model_dump(exclude={"password"})
    db_user = Utilisateur(
        **user_data, hash_mot_de_passe=get_password_hash(user_in.password)
    )
    session.add(db_user)
    await session.flush()  # Récupère l'ID sans commiter

    # 3. Créer la liaison pivot avec l'entreprise active
    link = UtilisateurEntreprise(
        id_utilisateur=db_user.id,
        id_entreprise=entreprise_id,
        est_admin=False,
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
    Crée un compte utilisateur "nu", sans rattachement initial à une entreprise.
    """
    statement = select(Utilisateur).where(Utilisateur.email == user_in.email)
    existing_user_result = await session.exec(statement)
    if existing_user_result.first():
        raise HTTPException(status_code=400, detail="Cet email est déjà utilisé")

    user_data = user_in.model_dump(exclude={"password"})
    db_user = Utilisateur(
        **user_data, hash_mot_de_passe=get_password_hash(user_in.password)
    )
    session.add(db_user)

    await session.commit()
    await session.refresh(db_user)
    return db_user
