"""
Endpoints d'administration de la plateforme : entreprises abonnées et
utilisateurs.

Router mince : toute la logique et les garde-fous vivent dans `services.py`.

**Protection.** Le garde `require_admin_plateforme` est posé une fois au niveau
du router : il s'applique donc à chacune de ces routes. Il ne dépend que du JWT
(flag `admin_plateforme`) et **jamais** du header `x-entreprise-id` — ces
endpoints transcendent volontairement l'isolation tenant, l'administrateur
agissant sur n'importe quelle entreprise, qu'il en soit membre ou non.
L'isolation reste entière pour les utilisateurs normaux, dont les routes
continuent de passer par `verify_tenant_access`.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlmodel.ext.asyncio.session import AsyncSession

from src.abonnements.models import EntrepriseAbonnement, StatutSouscription
from src.abonnements.schemas import EntrepriseAbonnementRead
from src.administration import services
from src.administration.schemas import (
    ChangementPlanAdminRequest,
    EntrepriseAdminDetail,
    EntrepriseAdminListItem,
    EntrepriseAdminRead,
    EntrepriseAdminUpdate,
    SuspensionRequest,
    UtilisateurAdminDetail,
    UtilisateurAdminListItem,
)
from src.auth.dependencies import require_admin_plateforme
from src.core.database import get_session
from src.core.pagination import Page, PaginationParams
from src.entreprises.models import Entreprise
from src.utilisateurs.models import Utilisateur

router = APIRouter(
    prefix="/administration",
    tags=["Administration Plateforme"],
    dependencies=[Depends(require_admin_plateforme)],
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "Authentification requise."},
        status.HTTP_403_FORBIDDEN: {
            "description": "Accès réservé aux administrateurs de la plateforme."
        },
    },
)

SessionDep = Annotated[AsyncSession, Depends(get_session)]
AdminDep = Annotated[Utilisateur, Depends(require_admin_plateforme)]
PaginationDep = Annotated[PaginationParams, Depends(PaginationParams)]


# ---------------------------------------------------------------------------
# Entreprises — lecture
# ---------------------------------------------------------------------------


@router.get("/entreprises", response_model=Page[EntrepriseAdminListItem])
async def list_entreprises(
    session: SessionDep,
    pagination: PaginationDep,
    recherche: Annotated[
        str | None,
        Query(description="Recherche sur la raison sociale ou le SIRET."),
    ] = None,
    est_actif: Annotated[
        bool | None,
        Query(description="Filtre sur l'état d'activité (faux = suspendue)."),
    ] = None,
    statut_abonnement: Annotated[
        StatutSouscription | None,
        Query(description="Filtre sur le statut de la souscription courante."),
    ] = None,
) -> Page[EntrepriseAdminListItem]:
    """
    Liste paginée des entreprises abonnées, avec leur plan et son statut, leur
    effectif et leur nombre de factures.
    """
    return await services.list_entreprises(
        session, pagination, recherche, est_actif, statut_abonnement
    )


@router.get(
    "/entreprises/{entreprise_id}",
    response_model=EntrepriseAdminDetail,
    responses={status.HTTP_404_NOT_FOUND: {"description": "Entreprise introuvable."}},
)
async def get_entreprise(
    entreprise_id: int, session: SessionDep
) -> EntrepriseAdminDetail:
    """
    Détail d'une entreprise : ses membres avec leur rôle, l'historique de ses
    souscriptions, et la volumétrie de ses données.

    Les compteurs renseignent directement sur ce qui bloquerait une suppression.
    """
    return await services.get_entreprise_detail(session, entreprise_id)


# ---------------------------------------------------------------------------
# Entreprises — modification
# ---------------------------------------------------------------------------


@router.patch(
    "/entreprises/{entreprise_id}",
    response_model=EntrepriseAdminRead,
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "Entreprise introuvable."},
        status.HTTP_409_CONFLICT: {
            "description": "SIRET déjà rattaché à une autre entreprise."
        },
        status.HTTP_422_UNPROCESSABLE_ENTITY: {
            "description": "SIRET invalide, ou forme juridique inconnue ou inactive."
        },
    },
)
async def update_entreprise(
    entreprise_id: int,
    payload: EntrepriseAdminUpdate,
    session: SessionDep,
) -> Entreprise:
    """
    Modifie l'identité légale d'une entreprise : raison sociale, SIRET, forme
    juridique. Aucun autre champ n'est modifiable par cette voie.

    La correction ne vaut que pour l'avenir : les factures déjà émises
    conservent l'instantané figé de leur émetteur et ne sont jamais réécrites.
    """
    return await services.update_entreprise(session, entreprise_id, payload)


@router.post(
    "/entreprises/{entreprise_id}/suspendre",
    response_model=EntrepriseAdminRead,
    responses={status.HTTP_404_NOT_FOUND: {"description": "Entreprise introuvable."}},
)
async def suspendre_entreprise(
    entreprise_id: int,
    payload: SuspensionRequest,
    session: SessionDep,
) -> Entreprise:
    """
    Suspend une entreprise : ses membres reçoivent un 403 sur toutes les routes
    tenant et sa souscription courante passe en `SUSPENDU`.

    Réversible et sans perte : c'est la réponse recommandée face à une
    entreprise dont les données interdisent la suppression.
    """
    return await services.suspendre_entreprise(session, entreprise_id, payload.motif)


@router.post(
    "/entreprises/{entreprise_id}/reactiver",
    response_model=EntrepriseAdminRead,
    responses={status.HTTP_404_NOT_FOUND: {"description": "Entreprise introuvable."}},
)
async def reactiver_entreprise(entreprise_id: int, session: SessionDep) -> Entreprise:
    """
    Rétablit l'accès d'une entreprise suspendue et lui restitue un abonnement
    actif (réactivé, ou rouvert sur le plan gratuit s'il avait été résilié).
    """
    return await services.reactiver_entreprise(session, entreprise_id)


@router.delete(
    "/entreprises/{entreprise_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        status.HTTP_403_FORBIDDEN: {
            "description": "Entreprise porteuse de factures émises : suppression "
            "définitivement impossible (inaltérabilité et conservation légale)."
        },
        status.HTTP_404_NOT_FOUND: {"description": "Entreprise introuvable."},
        status.HTTP_409_CONFLICT: {
            "description": "Entreprise contenant encore des données."
        },
    },
)
async def delete_entreprise(entreprise_id: int, session: SessionDep) -> None:
    """
    Supprime une entreprise **vierge de toute donnée** (doublon, compte de test,
    inscription abandonnée).

    Une seule facture émise rend la suppression définitivement impossible (403,
    sans contournement possible) ; toute autre donnée la bloque en 409. Dans les
    deux cas, la suspension est la voie à suivre.
    """
    await services.supprimer_entreprise(session, entreprise_id)


# ---------------------------------------------------------------------------
# Entreprises — abonnement
# ---------------------------------------------------------------------------


@router.post(
    "/entreprises/{entreprise_id}/abonnement/changer",
    response_model=EntrepriseAbonnementRead,
    responses={
        status.HTTP_404_NOT_FOUND: {
            "description": "Entreprise ou plan cible introuvable."
        },
        status.HTTP_409_CONFLICT: {
            "description": "Déjà sur ce plan, ou trop d'utilisateurs actifs pour "
            "le plan cible."
        },
    },
)
async def changer_plan(
    entreprise_id: int,
    payload: ChangementPlanAdminRequest,
    session: SessionDep,
) -> EntrepriseAbonnement:
    """
    Change le plan d'une entreprise ciblée par son identifiant.

    Même logique métier que la voie utilisateur (`/abonnements/me/changer`) :
    seule l'origine de l'entreprise diffère — un paramètre d'URL ici, le header
    tenant là-bas.
    """
    return await services.changer_plan(session, entreprise_id, payload.id_abonnement)


@router.post(
    "/entreprises/{entreprise_id}/abonnement/prolonger",
    response_model=EntrepriseAbonnementRead,
    responses={
        status.HTTP_404_NOT_FOUND: {
            "description": "Entreprise introuvable, ou aucune souscription active "
            "à prolonger."
        },
        status.HTTP_409_CONFLICT: {
            "description": "Le plan gratuit n'expire pas et ne peut pas être prolongé."
        },
    },
)
async def prolonger_abonnement(
    entreprise_id: int, session: SessionDep
) -> EntrepriseAbonnement:
    """Prolonge d'un mois l'abonnement payant d'une entreprise ciblée par son id."""
    return await services.prolonger_abonnement(session, entreprise_id)


@router.post(
    "/entreprises/{entreprise_id}/abonnement/resilier",
    response_model=EntrepriseAbonnementRead,
    responses={
        status.HTTP_404_NOT_FOUND: {
            "description": "Entreprise introuvable, ou aucune souscription à résilier."
        },
        status.HTTP_409_CONFLICT: {"description": "Souscription déjà résiliée."},
    },
)
async def resilier_abonnement(
    entreprise_id: int,
    payload: SuspensionRequest,
    session: SessionDep,
) -> EntrepriseAbonnement:
    """
    Résilie l'abonnement d'une entreprise et coupe son accès.

    À la différence de la suspension — mesure temporaire dont on attend la levée
    — la résiliation clôt la relation commerciale. Aucune donnée n'est touchée :
    `reactiver` rouvre le service sur le plan gratuit.
    """
    return await services.resilier_abonnement(session, entreprise_id, payload.motif)


# ---------------------------------------------------------------------------
# Utilisateurs
# ---------------------------------------------------------------------------


@router.get("/utilisateurs", response_model=Page[UtilisateurAdminListItem])
async def list_utilisateurs(
    session: SessionDep,
    pagination: PaginationDep,
    recherche: Annotated[
        str | None, Query(description="Recherche sur l'email, le nom ou le prénom.")
    ] = None,
    entreprise_id: Annotated[
        int | None, Query(description="Restreint aux membres de cette entreprise.")
    ] = None,
    est_actif: Annotated[
        bool | None, Query(description="Filtre sur l'état d'activité du compte.")
    ] = None,
    admin_plateforme: Annotated[
        bool | None, Query(description="Filtre sur le statut d'admin plateforme.")
    ] = None,
) -> Page[UtilisateurAdminListItem]:
    """
    Liste paginée des utilisateurs, toutes entreprises confondues, avec leurs
    rattachements.
    """
    return await services.list_utilisateurs(
        session, pagination, recherche, entreprise_id, est_actif, admin_plateforme
    )


@router.get(
    "/utilisateurs/{utilisateur_id}",
    response_model=UtilisateurAdminDetail,
    responses={status.HTTP_404_NOT_FOUND: {"description": "Utilisateur introuvable."}},
)
async def get_utilisateur(
    utilisateur_id: int, session: SessionDep
) -> UtilisateurAdminDetail:
    """
    Détail d'un utilisateur : ses entreprises de rattachement et la volumétrie
    des données qu'il a créées (laquelle conditionne sa suppression).
    """
    return await services.get_utilisateur_detail(session, utilisateur_id)


@router.post(
    "/utilisateurs/{utilisateur_id}/desactiver",
    response_model=UtilisateurAdminDetail,
    responses={
        status.HTTP_403_FORBIDDEN: {
            "description": "Auto-désactivation, ou compte protégé."
        },
        status.HTTP_404_NOT_FOUND: {"description": "Utilisateur introuvable."},
    },
)
async def desactiver_utilisateur(
    utilisateur_id: int,
    session: SessionDep,
    current_admin: AdminDep,
) -> UtilisateurAdminDetail:
    """
    Désactive un compte utilisateur — la voie recommandée, réversible et sans
    perte de données.

    L'effet est immédiat : un compte inactif est refusé à l'authentification,
    quel que soit le jeton présenté. Un administrateur ne peut pas se désactiver
    lui-même, et le compte racine protégé reste intouchable.
    """
    await services.definir_activite_utilisateur(
        session, utilisateur_id, False, current_admin
    )
    return await services.get_utilisateur_detail(session, utilisateur_id)


@router.post(
    "/utilisateurs/{utilisateur_id}/reactiver",
    response_model=UtilisateurAdminDetail,
    responses={status.HTTP_404_NOT_FOUND: {"description": "Utilisateur introuvable."}},
)
async def reactiver_utilisateur(
    utilisateur_id: int,
    session: SessionDep,
    current_admin: AdminDep,
) -> UtilisateurAdminDetail:
    """
    Réactive un compte utilisateur.

    N'est pas soumise à la limite d'utilisateurs du plan : l'administrateur de
    plateforme agit en support. Cette limite continue de s'appliquer
    intégralement aux utilisateurs normaux.
    """
    await services.definir_activite_utilisateur(
        session, utilisateur_id, True, current_admin
    )
    return await services.get_utilisateur_detail(session, utilisateur_id)


@router.delete(
    "/utilisateurs/{utilisateur_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        status.HTTP_403_FORBIDDEN: {
            "description": "Compte protégé, ou auto-suppression."
        },
        status.HTTP_404_NOT_FOUND: {"description": "Utilisateur introuvable."},
        status.HTTP_409_CONFLICT: {
            "description": "Dernier administrateur de plateforme, seul "
            "administrateur d'une entreprise peuplée, ou auteur de données "
            "comptables."
        },
    },
)
async def delete_utilisateur(
    utilisateur_id: int,
    session: SessionDep,
    current_admin: AdminDep,
) -> None:
    """
    Supprime physiquement un compte — opération de dernier recours, en pratique
    réservée aux comptes créés puis jamais utilisés.

    Refusée si le compte est protégé, s'il s'agit du sien, s'il est le dernier
    administrateur de plateforme, s'il administre seul une entreprise peuplée,
    ou s'il a créé la moindre donnée comptable. Dans ce dernier cas, la
    désactivation est la voie à suivre : savoir qui a émis une facture fait
    partie de la piste d'audit.
    """
    await services.supprimer_utilisateur(session, utilisateur_id, current_admin)
