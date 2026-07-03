from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlmodel import and_, or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.abonnements import services as abonnements_services
from src.auth.dependencies import (
    RequirePermission,
    get_current_user,
    verify_tenant_access,
)
from src.auth.models import Role, UtilisateurRole
from src.auth.schemas import MessageResponse
from src.core.database import get_session
from src.core.security import create_access_token, get_password_hash
from src.entreprises.models import UtilisateurEntreprise
from src.utilisateurs.models import Utilisateur
from src.utilisateurs.schemas import (
    ChangementEmailRequest,
    ChangementEmailResponse,
    ChangementMotDePasseRequest,
    ProfilUpdate,
    UtilisateurCreate,
    UtilisateurRead,
    UtilisateurTeamUpdate,
)
from src.utilisateurs.services import change_email, change_password

router = APIRouter(prefix="/utilisateurs", tags=["Gestion des Utilisateurs"])


async def _membre_read_dict(
    session: AsyncSession, db_user: Utilisateur, entreprise_id: int
) -> dict[str, Any]:
    """
    Enrichit un utilisateur avec son rôle métier et son statut admin dans le
    contexte de l'entreprise active, pour renvoyer un schéma de lecture complet.

    Indispensable pour que le client connaisse l'`est_admin` courant et ne le
    réinitialise pas par erreur lors d'une édition.
    """
    statement = (
        select(UtilisateurEntreprise.est_admin, Role.libelle)
        .outerjoin(
            UtilisateurRole,
            and_(
                UtilisateurRole.id_utilisateur == UtilisateurEntreprise.id_utilisateur,
                or_(
                    UtilisateurRole.id_entreprise == entreprise_id,
                    UtilisateurRole.id_entreprise == None,  # noqa: E711
                ),
            ),
        )
        .outerjoin(Role, UtilisateurRole.id_role == Role.id)  # type: ignore
        .where(
            UtilisateurEntreprise.id_utilisateur == db_user.id,
            UtilisateurEntreprise.id_entreprise == entreprise_id,
        )
    )
    row = (await session.exec(statement)).first()

    user_dict = db_user.model_dump()
    if row is not None:
        user_dict["est_admin"] = row[0]
        user_dict["role"] = row[1]
    return user_dict


@router.get("/me", response_model=UtilisateurRead)
async def get_my_profile(
    current_user: Annotated[Utilisateur, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    x_entreprise_id: Annotated[
        int | None,
        Header(
            title="ID de l'entreprise",
            description="Identifiant de l'entreprise (tenant) active. Optionnel : "
            "s'il est fourni et que l'utilisateur y appartient, `est_admin` et "
            "`role` sont renseignés pour cette entreprise ; sinon ils restent nuls.",
        ),
    ] = None,
) -> Any:
    """
    Récupère le profil de l'utilisateur actuellement connecté.

    Le header `x-entreprise-id` est optionnel : absent (ex. utilisateur sans
    entreprise ou juste après login), le profil brut est renvoyé et `est_admin`
    reste nul. Présent, le profil est enrichi de `est_admin`/`role` dans le
    contexte de cette entreprise — uniquement si l'utilisateur en est membre
    (aucune usurpation possible sinon).
    """
    if x_entreprise_id is None:
        return current_user
    return await _membre_read_dict(session, current_user, x_entreprise_id)


@router.patch("/me", response_model=UtilisateurRead)
async def update_my_profile(
    user_in: ProfilUpdate,
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


@router.post(
    "/me/changer-mot-de-passe",
    response_model=MessageResponse,
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "description": "Mot de passe actuel incorrect, ou nouveau mot de passe "
            "identique à l'actuel.",
        },
        status.HTTP_422_UNPROCESSABLE_ENTITY: {
            "description": "Validation échouée (ex : nouveau mot de passe de moins "
            "de 8 caractères).",
        },
    },
)
async def change_my_password(
    payload: ChangementMotDePasseRequest,
    current_user: Annotated[Utilisateur, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MessageResponse:
    """
    Permet à l'utilisateur connecté de changer son propre mot de passe.

    Exige le mot de passe actuel (aucun changement à l'aveugle sur une session
    ouverte) et invalide les liens de réinitialisation en cours. Distinct du flux
    « mot de passe oublié », qui repose lui sur un token reçu par email et ne
    nécessite pas d'être authentifié. Aucun header tenant n'est requis.
    """
    await change_password(
        session,
        current_user,
        payload.mot_de_passe_actuel,
        payload.nouveau_mot_de_passe,
    )
    return MessageResponse(message="Votre mot de passe a été mis à jour.")


@router.post(
    "/me/changer-email",
    response_model=ChangementEmailResponse,
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "description": "Mot de passe actuel incorrect, ou nouvel email "
            "identique à l'actuel.",
        },
        status.HTTP_409_CONFLICT: {
            "description": "Cet email est déjà utilisé par un autre compte.",
        },
        status.HTTP_422_UNPROCESSABLE_ENTITY: {
            "description": "Validation échouée (ex : format d'email invalide).",
        },
    },
)
async def change_my_email(
    payload: ChangementEmailRequest,
    current_user: Annotated[Utilisateur, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ChangementEmailResponse:
    """
    Permet à l'utilisateur connecté de changer son propre email.

    L'email étant l'identifiant de connexion, le mot de passe actuel est exigé
    (aucun changement à l'aveugle sur une session ouverte). Un email déjà pris
    par un autre compte est refusé en 409. Aucun header tenant n'est requis.

    L'email servant de `sub` au JWT, l'ancien token devient caduc : un token
    frais (sur le nouvel email) est renvoyé pour poursuivre la session sans
    reconnexion.
    """
    await change_email(
        session,
        current_user,
        payload.mot_de_passe_actuel,
        payload.nouvel_email,
    )
    access_token = create_access_token(data={"sub": current_user.email})
    return ChangementEmailResponse(
        message="Votre email a été mis à jour.",
        access_token=access_token,
    )


@router.get("/", response_model=list[UtilisateurRead])
async def list_team_members(
    entreprise_id: Annotated[int, Depends(verify_tenant_access)],
    _: Annotated[Utilisateur, Depends(RequirePermission("users:read"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Any:
    """
    Liste tous les utilisateurs rattachés à l'entreprise active (l'équipe).
    """
    statement = (
        select(Utilisateur, Role.libelle, UtilisateurEntreprise.est_admin)
        .join(
            UtilisateurEntreprise,
            Utilisateur.id == UtilisateurEntreprise.id_utilisateur,  # type: ignore
        )
        .outerjoin(
            UtilisateurRole,
            and_(
                Utilisateur.id == UtilisateurRole.id_utilisateur,
                or_(
                    UtilisateurRole.id_entreprise == entreprise_id,
                    UtilisateurRole.id_entreprise == None,  # noqa: E711
                ),
            ),
        )
        .outerjoin(Role, UtilisateurRole.id_role == Role.id)  # type: ignore
        .where(UtilisateurEntreprise.id_entreprise == entreprise_id)
    )

    results = await session.exec(statement)
    membres = []
    for user, role_libelle, est_admin in results:
        user_dict = user.model_dump()
        user_dict["role"] = role_libelle
        user_dict["est_admin"] = est_admin
        membres.append(user_dict)

    return membres


@router.post(
    "/",
    response_model=UtilisateurRead,
    status_code=status.HTTP_201_CREATED,
    responses={
        status.HTTP_409_CONFLICT: {
            "description": "La limite d'utilisateurs du plan actif est atteinte.",
        },
    },
)
async def create_team_member(
    user_in: UtilisateurCreate,
    entreprise_id: Annotated[int, Depends(verify_tenant_access)],
    _: Annotated[Utilisateur, Depends(RequirePermission("users:create"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Any:
    """
    Crée un nouvel utilisateur et le rattache automatiquement à l'entreprise actuelle.

    Refuse la création (409) si l'entreprise atteint déjà la limite
    d'utilisateurs de son plan actif — sans jamais toucher aux comptes existants.
    """
    # 1. Garde-fou : ne pas dépasser la limite du plan actif (ajout d'un actif).
    await abonnements_services.ensure_can_add_active_user(session, entreprise_id)

    # 2. Vérification email...
    statement = select(Utilisateur).where(Utilisateur.email == user_in.email)
    existing_user_result = await session.exec(statement)
    if existing_user_result.first():
        raise HTTPException(status_code=400, detail="Cet email est déjà utilisé")

    # 2. Création de l'utilisateur (On exclut bien les champs des tables pivots)
    user_data = user_in.model_dump(exclude={"password", "id_role", "est_admin"})
    db_user = Utilisateur(
        **user_data, hash_mot_de_passe=get_password_hash(user_in.password)
    )
    session.add(db_user)
    await session.flush()

    # 3. Liaison Entreprise + Droit d'administration (Rôle Applicatif)
    link = UtilisateurEntreprise(
        id_utilisateur=db_user.id,
        id_entreprise=entreprise_id,
        est_admin=user_in.est_admin,
    )
    session.add(link)

    # 4. Liaison Rôle Métier (CORRECTION DU BUG)
    role_link = UtilisateurRole(
        id_utilisateur=db_user.id, id_role=user_in.id_role, id_entreprise=entreprise_id
    )
    session.add(role_link)

    # 5. Validation globale
    await session.commit()
    await session.refresh(db_user)
    return await _membre_read_dict(session, db_user, entreprise_id)


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


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_team_member(
    user_id: int,
    entreprise_id: Annotated[int, Depends(verify_tenant_access)],
    _: Annotated[Utilisateur, Depends(RequirePermission("users:delete"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    # 1. On cherche l'utilisateur
    statement = select(Utilisateur).where(Utilisateur.id == user_id)
    db_user = (await session.exec(statement)).first()

    if not db_user:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable.")

    # Le compte racine protégé n'est supprimable par personne.
    if db_user.compte_protege:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Ce compte est protégé et ne peut pas être supprimé.",
        )

    # 2. Comme on a mis ondelete="CASCADE" dans les modèles,
    # supprimer l'utilisateur supprimera automatiquement les lignes
    # dans UtilisateurRole et UtilisateurEntreprise.
    await session.delete(db_user)
    await session.commit()
    return None


@router.patch(
    "/{user_id}",
    response_model=UtilisateurRead,
    responses={
        status.HTTP_409_CONFLICT: {
            "description": "Réactivation refusée : limite d'utilisateurs du plan "
            "actif atteinte.",
        },
    },
)
async def update_team_member(
    user_id: int,
    user_in: UtilisateurTeamUpdate,
    entreprise_id: Annotated[int, Depends(verify_tenant_access)],
    _: Annotated[Utilisateur, Depends(RequirePermission("users:update"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Any:
    """Modifie les informations d'un
    collaborateur (incluant ses rôles et accès admin).

    Réactiver un membre (`est_actif` False -> True) est refusé en 409 si
    l'entreprise est déjà à la limite d'utilisateurs de son plan actif. La
    désactivation et les autres modifications restent toujours autorisées.
    """

    # 1. Vérifier que l'utilisateur existe et appartient bien à l'entreprise
    statement = (
        select(Utilisateur)
        .join(UtilisateurEntreprise)
        .where(
            UtilisateurEntreprise.id_utilisateur == user_id,
            UtilisateurEntreprise.id_entreprise == entreprise_id,
        )
    )
    db_user = (await session.exec(statement)).first()
    if not db_user:
        raise HTTPException(
            status_code=404, detail="Utilisateur introuvable dans cette entreprise."
        )

    # 1bis. Garde-fou réactivation (est_actif False -> True) : évaluer la limite
    # AVANT toute mutation de db_user, car la réconciliation interne du garde-fou
    # peut committer (bascule vers le gratuit) et persisterait des changements
    # partiels sinon.
    est_reactivation = user_in.est_actif is True and not db_user.est_actif
    if est_reactivation:
        await abonnements_services.ensure_can_add_active_user(session, entreprise_id)

    # 2. Mise à jour dynamique des infos de base de l'utilisateur
    # On exclut les champs qui ne sont pas dans la table 'utilisateur'
    # pour éviter les erreurs SQLModel
    user_data = user_in.model_dump(
        exclude_unset=True, exclude={"password", "id_role", "est_admin"}
    )
    for key, value in user_data.items():
        setattr(db_user, key, value)

    # 3. Traitement spécifique du mot de passe s'il a été fourni
    if user_in.password:
        db_user.hash_mot_de_passe = get_password_hash(user_in.password)

    session.add(db_user)

    # 4. Traitement spécifique du rôle métier (table pivot UtilisateurRole)
    if user_in.id_role is not None:
        stmt_role = select(UtilisateurRole).where(
            UtilisateurRole.id_utilisateur == user_id,
            UtilisateurRole.id_entreprise == entreprise_id,
        )
        link_role = (await session.exec(stmt_role)).first()

        if link_role:
            link_role.id_role = user_in.id_role
        else:
            # S'il n'avait pas de rôle défini pour cette entreprise, on crée la liaison
            link_role = UtilisateurRole(
                id_utilisateur=user_id,
                id_role=user_in.id_role,
                id_entreprise=entreprise_id,
            )
        session.add(link_role)

    # 5. Traitement spécifique des droits admin (table pivot UtilisateurEntreprise)
    if user_in.est_admin is not None:
        stmt_ent = select(UtilisateurEntreprise).where(
            UtilisateurEntreprise.id_utilisateur == user_id,
            UtilisateurEntreprise.id_entreprise == entreprise_id,
        )
        link_ent = (await session.exec(stmt_ent)).first()
        if link_ent:
            link_ent.est_admin = user_in.est_admin
            session.add(link_ent)

    # 6. Validation globale de la transaction
    await session.commit()
    await session.refresh(db_user)

    return await _membre_read_dict(session, db_user, entreprise_id)
