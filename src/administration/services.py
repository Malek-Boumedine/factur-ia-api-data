"""
Logique métier de l'administration de plateforme.

Router mince : toutes les règles, agrégations et garde-fous vivent ici. Deux
principes structurent ce module :

1. **Prudence sur les suppressions.** La désactivation (utilisateur) et la
   suspension (entreprise) sont les voies normales, réversibles et sans perte.
   La suppression physique n'est acceptée que sur des enregistrements vierges
   de toute donnée. Une facture sortie de l'état brouillon rend la suppression
   de son entreprise définitivement impossible : l'inaltérabilité et
   l'obligation de conservation priment sur toute demande d'effacement, sans
   paramètre de contournement.

2. **Agrégations groupées.** Les listes assemblent leurs compteurs en un nombre
   fixe de requêtes (indépendant de la taille de page), jamais une requête par
   ligne.
"""

from datetime import UTC, date, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import case, delete, func, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.abonnements import services as abonnements_services
from src.abonnements.models import Abonnement, EntrepriseAbonnement, StatutSouscription
from src.administration.schemas import (
    CompteursEntreprise,
    CompteursUtilisateur,
    EntrepriseAdminDetail,
    EntrepriseAdminListItem,
    EntrepriseAdminUpdate,
    MembreEntrepriseRead,
    RattachementEntrepriseRead,
    SouscriptionAdminRead,
    UtilisateurAdminDetail,
    UtilisateurAdminListItem,
)
from src.audit.models import JournalAudit
from src.auth.models import Role, UtilisateurRole
from src.catalogue_produits.models import Catalogue
from src.clients.models import Client
from src.core.db_errors import UniqueConflict, conflict_from_integrity_error
from src.core.pagination import Page, PaginationParams, apply_search, paginate
from src.documents.models import Document
from src.entreprises.models import Entreprise, RefFormeJuridique, UtilisateurEntreprise
from src.factures.models import Facture, Paiement, StatutFacture
from src.notifications.models import Notification
from src.utilisateurs.models import Utilisateur

# Libellé du statut de facture « brouillon » (référentiel seedé). Une facture
# portant un autre statut est considérée comme scellée.
_STATUT_BROUILLON_LIBELLE = "brouillon"

_SIRET_CONFLICTS = [
    UniqueConflict("siret", "Ce SIRET est déjà rattaché à une autre entreprise."),
]


# ---------------------------------------------------------------------------
# Helpers de chargement
# ---------------------------------------------------------------------------


async def _get_entreprise_or_404(
    session: AsyncSession, entreprise_id: int
) -> Entreprise:
    """Charge une entreprise par son id ou lève une 404."""
    entreprise = await session.get(Entreprise, entreprise_id)
    if entreprise is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Entreprise introuvable."
        )
    return entreprise


async def _get_utilisateur_or_404(
    session: AsyncSession, utilisateur_id: int
) -> Utilisateur:
    """Charge un utilisateur par son id ou lève une 404."""
    utilisateur = await session.get(Utilisateur, utilisateur_id)
    if utilisateur is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Utilisateur introuvable."
        )
    return utilisateur


async def _count(session: AsyncSession, statement: Any) -> int:
    """Compte les lignes correspondant à une requête de sélection."""
    result = await session.exec(select(func.count()).select_from(statement.subquery()))
    return int(result.one())


async def _ids_statuts_scelles(session: AsyncSession) -> list[int] | None:
    """
    Identifiants des statuts de facture considérés comme scellés (tout sauf
    « brouillon »).

    Renvoie ``None`` si le référentiel est introuvable ou vide : l'appelant doit
    alors traiter *toutes* les factures comme scellées. Ce choix fait échouer le
    contrôle du côté sûr — une configuration incomplète ne doit jamais aboutir à
    autoriser la suppression de données réglementaires.
    """
    result = await session.exec(select(StatutFacture))
    statuts = list(result.all())
    if not statuts:
        return None
    if not any(s.libelle.lower() == _STATUT_BROUILLON_LIBELLE for s in statuts):
        return None
    return [
        s.id
        for s in statuts
        if s.id is not None and s.libelle.lower() != _STATUT_BROUILLON_LIBELLE
    ]


# ---------------------------------------------------------------------------
# Lecture : entreprises
# ---------------------------------------------------------------------------


async def _souscriptions_par_entreprise(
    session: AsyncSession, entreprise_ids: list[int]
) -> dict[int, list[SouscriptionAdminRead]]:
    """
    Souscriptions des entreprises données, groupées par entreprise et triées du
    plus récent au plus ancien.

    Une seule requête pour toute la page (jointure sur le plan pour récupérer
    libellé et tarif), puis regroupement en mémoire.

    L'ordre est celui des identifiants décroissants, et non des dates : les
    souscriptions sont toujours ajoutées, jamais réécrites, si bien que le plus
    grand identifiant est la souscription courante. Cette définition est
    exactement celle qu'emploie le filtre SQL par statut — les deux ne peuvent
    donc pas diverger.
    """
    if not entreprise_ids:
        return {}

    statement = (
        select(EntrepriseAbonnement, Abonnement)
        .join(
            Abonnement,
            col(Abonnement.id) == EntrepriseAbonnement.id_abonnement,
            isouter=True,
        )
        .where(col(EntrepriseAbonnement.id_entreprise).in_(entreprise_ids))
        .order_by(col(EntrepriseAbonnement.id).desc())
    )
    rows = (await session.exec(statement)).all()

    groupes: dict[int, list[SouscriptionAdminRead]] = {}
    for souscription, plan in rows:
        if souscription.id is None:
            continue
        groupes.setdefault(souscription.id_entreprise, []).append(
            SouscriptionAdminRead(
                id=souscription.id,
                id_abonnement=souscription.id_abonnement,
                libelle_abonnement=plan.libelle if plan is not None else None,
                tarif=plan.tarif if plan is not None else None,
                date_debut=souscription.date_debut,
                date_fin=souscription.date_fin,
                statut=souscription.statut,
                date_creation=souscription.date_creation,
            )
        )
    return groupes


async def _effectifs_par_entreprise(
    session: AsyncSession, entreprise_ids: list[int]
) -> dict[int, tuple[int, int]]:
    """Nombre d'utilisateurs (total, actifs) par entreprise, en une requête."""
    if not entreprise_ids:
        return {}

    statement = (
        select(
            UtilisateurEntreprise.id_entreprise,
            func.count(),
            func.sum(case((col(Utilisateur.est_actif), 1), else_=0)),
        )
        .join(
            Utilisateur,
            col(Utilisateur.id) == UtilisateurEntreprise.id_utilisateur,
        )
        .where(col(UtilisateurEntreprise.id_entreprise).in_(entreprise_ids))
        .group_by(col(UtilisateurEntreprise.id_entreprise))
    )
    rows = (await session.exec(statement)).all()
    return {
        id_entreprise: (int(total), int(actifs or 0))
        for id_entreprise, total, actifs in rows
    }


async def _factures_par_entreprise(
    session: AsyncSession, entreprise_ids: list[int]
) -> dict[int, int]:
    """Nombre de factures par entreprise, en une requête."""
    if not entreprise_ids:
        return {}

    statement = (
        select(Facture.id_entreprise, func.count())
        .where(col(Facture.id_entreprise).in_(entreprise_ids))
        .group_by(col(Facture.id_entreprise))
    )
    rows = (await session.exec(statement)).all()
    return {id_entreprise: int(total) for id_entreprise, total in rows}


async def list_entreprises(
    session: AsyncSession,
    params: PaginationParams,
    recherche: str | None = None,
    est_actif: bool | None = None,
    statut_abonnement: StatutSouscription | None = None,
) -> Page[EntrepriseAdminListItem]:
    """
    Liste paginée des entreprises abonnées, avec plan, effectif et volumétrie.

    Les compteurs sont assemblés en quatre requêtes au total (page, effectifs,
    factures, souscriptions), quelle que soit la taille de la page : aucune
    requête par ligne.

    Filtres : recherche sur la raison sociale et le SIRET, état d'activité, et
    statut de la souscription courante. Ce dernier est appliqué en SQL, avant
    pagination, pour que le total renvoyé corresponde bien aux lignes filtrées.
    """
    statement = select(Entreprise)
    statement = apply_search(
        statement, [col(Entreprise.nom_entreprise), col(Entreprise.siret)], recherche
    )
    if est_actif is not None:
        statement = statement.where(col(Entreprise.est_actif).is_(est_actif))
    if statut_abonnement is not None:
        statement = _filtrer_par_statut_souscription(statement, statut_abonnement)
    statement = statement.order_by(col(Entreprise.id).desc())

    page = await paginate(session, statement, params)
    items = await _assembler_lignes_entreprises(session, list(page.items))

    return Page[EntrepriseAdminListItem](
        items=items, total=page.total, skip=page.skip, limit=page.limit
    )


def _filtrer_par_statut_souscription(statement: Any, statut: StatutSouscription) -> Any:
    """
    Restreint une requête sur les entreprises dont la souscription *courante*
    porte le statut donné.

    La souscription courante est celle de plus grand identifiant : les
    souscriptions sont ajoutées et jamais réécrites (le changement de plan
    clôture l'ancienne et en crée une nouvelle), donc le dernier identifiant est
    toujours l'état présent. Même définition que `_souscriptions_par_entreprise`.
    """
    derniere = (
        select(
            EntrepriseAbonnement.id_entreprise,
            func.max(col(EntrepriseAbonnement.id)).label("id_courante"),
        )
        .group_by(col(EntrepriseAbonnement.id_entreprise))
        .subquery()
    )
    return (
        statement.join(derniere, col(Entreprise.id) == derniere.c.id_entreprise)
        .join(
            EntrepriseAbonnement,
            col(EntrepriseAbonnement.id) == derniere.c.id_courante,
        )
        .where(EntrepriseAbonnement.statut == statut)
    )


async def _assembler_lignes_entreprises(
    session: AsyncSession, entreprises: list[Entreprise]
) -> list[EntrepriseAdminListItem]:
    """Enrichit une page d'entreprises de ses agrégats (requêtes groupées)."""
    entreprise_ids = [e.id for e in entreprises if e.id is not None]

    effectifs = await _effectifs_par_entreprise(session, entreprise_ids)
    factures = await _factures_par_entreprise(session, entreprise_ids)
    souscriptions = await _souscriptions_par_entreprise(session, entreprise_ids)
    formes = await _libelles_formes_juridiques(session, entreprises)

    lignes: list[EntrepriseAdminListItem] = []
    for entreprise in entreprises:
        if entreprise.id is None:
            continue
        total, actifs = effectifs.get(entreprise.id, (0, 0))
        historique = souscriptions.get(entreprise.id, [])
        lignes.append(
            EntrepriseAdminListItem(
                id=entreprise.id,
                nom_entreprise=entreprise.nom_entreprise,
                siret=entreprise.siret,
                id_forme_juridique=entreprise.id_forme_juridique,
                forme_juridique=formes.get(entreprise.id_forme_juridique)
                if entreprise.id_forme_juridique is not None
                else None,
                date_creation=entreprise.date_creation,
                est_actif=entreprise.est_actif,
                date_suspension=entreprise.date_suspension,
                motif_suspension=entreprise.motif_suspension,
                souscription=historique[0] if historique else None,
                nombre_utilisateurs=total,
                nombre_utilisateurs_actifs=actifs,
                nombre_factures=factures.get(entreprise.id, 0),
            )
        )
    return lignes


async def _libelles_formes_juridiques(
    session: AsyncSession, entreprises: list[Entreprise]
) -> dict[int, str]:
    """Libellés des formes juridiques référencées par une page d'entreprises."""
    ids = {
        e.id_forme_juridique for e in entreprises if e.id_forme_juridique is not None
    }
    if not ids:
        return {}
    result = await session.exec(
        select(RefFormeJuridique).where(col(RefFormeJuridique.id).in_(list(ids)))
    )
    return {f.id: f.libelle for f in result.all() if f.id is not None}


async def _membres_entreprise(
    session: AsyncSession, entreprise_id: int
) -> list[MembreEntrepriseRead]:
    """
    Membres d'une entreprise avec leur droit d'administration et leur rôle
    métier dans cette entreprise (rôles globaux inclus).
    """
    statement = (
        select(Utilisateur, UtilisateurEntreprise.est_admin, Role.libelle)
        .join(
            UtilisateurEntreprise,
            col(Utilisateur.id) == UtilisateurEntreprise.id_utilisateur,
        )
        .outerjoin(
            UtilisateurRole,
            (col(UtilisateurRole.id_utilisateur) == col(Utilisateur.id))
            & (
                (col(UtilisateurRole.id_entreprise) == entreprise_id)
                | (col(UtilisateurRole.id_entreprise).is_(None))
            ),
        )
        .outerjoin(Role, col(UtilisateurRole.id_role) == col(Role.id))
        .where(UtilisateurEntreprise.id_entreprise == entreprise_id)
        .order_by(col(Utilisateur.nom), col(Utilisateur.prenom))
    )
    rows = (await session.exec(statement)).all()

    membres: list[MembreEntrepriseRead] = []
    for utilisateur, est_admin, role_libelle in rows:
        if utilisateur.id is None:
            continue
        membres.append(
            MembreEntrepriseRead(
                id=utilisateur.id,
                nom=utilisateur.nom,
                prenom=utilisateur.prenom,
                email=utilisateur.email,
                est_actif=utilisateur.est_actif,
                admin_plateforme=utilisateur.admin_plateforme,
                compte_protege=utilisateur.compte_protege,
                est_admin=bool(est_admin),
                role=role_libelle,
                date_derniere_connexion=utilisateur.date_derniere_connexion,
            )
        )
    return membres


async def compteurs_entreprise(
    session: AsyncSession, entreprise_id: int
) -> CompteursEntreprise:
    """
    Volumétrie des données rattachées à une entreprise.

    `factures_scellees` est le compteur décisif : il conditionne le refus
    définitif de suppression. Si le référentiel des statuts est inexploitable,
    toutes les factures y sont comptées (échec du côté sûr).
    """
    statuts_scelles = await _ids_statuts_scelles(session)

    base = select(Facture).where(Facture.id_entreprise == entreprise_id)
    factures_total = await _count(session, base)

    if statuts_scelles is None:
        factures_scellees = factures_total
    elif not statuts_scelles:
        factures_scellees = 0
    else:
        factures_scellees = await _count(
            session, base.where(col(Facture.id_statut).in_(statuts_scelles))
        )

    return CompteursEntreprise(
        factures_total=factures_total,
        factures_brouillon=factures_total - factures_scellees,
        factures_scellees=factures_scellees,
        clients=await _count(
            session, select(Client).where(Client.id_entreprise == entreprise_id)
        ),
        documents=await _count(
            session, select(Document).where(Document.id_entreprise == entreprise_id)
        ),
        produits=await _count(
            session, select(Catalogue).where(Catalogue.id_entreprise == entreprise_id)
        ),
    )


async def get_entreprise_detail(
    session: AsyncSession, entreprise_id: int
) -> EntrepriseAdminDetail:
    """Détail complet d'une entreprise : membres, abonnements, volumétrie."""
    entreprise = await _get_entreprise_or_404(session, entreprise_id)

    lignes = await _assembler_lignes_entreprises(session, [entreprise])
    ligne = lignes[0]
    historique = (await _souscriptions_par_entreprise(session, [entreprise_id])).get(
        entreprise_id, []
    )

    return EntrepriseAdminDetail(
        **ligne.model_dump(),
        membres=await _membres_entreprise(session, entreprise_id),
        souscriptions=historique,
        compteurs=await compteurs_entreprise(session, entreprise_id),
    )


# ---------------------------------------------------------------------------
# Lecture : utilisateurs
# ---------------------------------------------------------------------------


async def _rattachements_par_utilisateur(
    session: AsyncSession, utilisateur_ids: list[int]
) -> dict[int, list[RattachementEntrepriseRead]]:
    """Entreprises de rattachement des utilisateurs donnés, en une requête."""
    if not utilisateur_ids:
        return {}

    statement = (
        select(UtilisateurEntreprise, Entreprise)
        .join(
            Entreprise,
            col(Entreprise.id) == UtilisateurEntreprise.id_entreprise,
        )
        .where(col(UtilisateurEntreprise.id_utilisateur).in_(utilisateur_ids))
        .order_by(col(Entreprise.nom_entreprise))
    )
    rows = (await session.exec(statement)).all()

    groupes: dict[int, list[RattachementEntrepriseRead]] = {}
    for lien, entreprise in rows:
        if entreprise.id is None:
            continue
        groupes.setdefault(lien.id_utilisateur, []).append(
            RattachementEntrepriseRead(
                id_entreprise=entreprise.id,
                nom_entreprise=entreprise.nom_entreprise,
                est_admin=lien.est_admin,
                entreprise_active=entreprise.est_actif,
            )
        )
    return groupes


async def list_utilisateurs(
    session: AsyncSession,
    params: PaginationParams,
    recherche: str | None = None,
    entreprise_id: int | None = None,
    est_actif: bool | None = None,
    admin_plateforme: bool | None = None,
) -> Page[UtilisateurAdminListItem]:
    """
    Liste paginée des utilisateurs de la plateforme, toutes entreprises
    confondues.

    Recherche sur l'email, le nom et le prénom. Le filtre `entreprise_id`
    restreint aux membres d'une entreprise donnée (jointure sur le pivot). Les
    rattachements sont chargés en une requête pour toute la page.
    """
    statement = select(Utilisateur)
    if entreprise_id is not None:
        statement = statement.join(
            UtilisateurEntreprise,
            col(Utilisateur.id) == UtilisateurEntreprise.id_utilisateur,
        ).where(UtilisateurEntreprise.id_entreprise == entreprise_id)

    statement = apply_search(
        statement,
        [col(Utilisateur.email), col(Utilisateur.nom), col(Utilisateur.prenom)],
        recherche,
    )
    if est_actif is not None:
        statement = statement.where(col(Utilisateur.est_actif).is_(est_actif))
    if admin_plateforme is not None:
        statement = statement.where(
            col(Utilisateur.admin_plateforme).is_(admin_plateforme)
        )
    statement = statement.order_by(col(Utilisateur.id).desc())

    page = await paginate(session, statement, params)
    utilisateurs: list[Utilisateur] = list(page.items)
    ids = [u.id for u in utilisateurs if u.id is not None]
    rattachements = await _rattachements_par_utilisateur(session, ids)

    items = [
        UtilisateurAdminListItem(
            id=u.id,
            nom=u.nom,
            prenom=u.prenom,
            email=u.email,
            telephone=u.telephone,
            est_actif=u.est_actif,
            admin_plateforme=u.admin_plateforme,
            compte_protege=u.compte_protege,
            date_creation=u.date_creation,
            date_derniere_connexion=u.date_derniere_connexion,
            entreprises=rattachements.get(u.id, []),
        )
        for u in utilisateurs
        if u.id is not None
    ]

    return Page[UtilisateurAdminListItem](
        items=items, total=page.total, skip=page.skip, limit=page.limit
    )


async def compteurs_utilisateur(
    session: AsyncSession, utilisateur_id: int
) -> CompteursUtilisateur:
    """Volumétrie des données créées par un utilisateur (toutes entreprises)."""
    return CompteursUtilisateur(
        factures_creees=await _count(
            session, select(Facture).where(Facture.id_createur == utilisateur_id)
        ),
        paiements_crees=await _count(
            session, select(Paiement).where(Paiement.id_createur == utilisateur_id)
        ),
        clients_crees=await _count(
            session,
            select(Client).where(
                or_(
                    col(Client.id_createur) == utilisateur_id,
                    col(Client.id_modificateur) == utilisateur_id,
                )
            ),
        ),
        documents_charges=await _count(
            session, select(Document).where(Document.id_utilisateur == utilisateur_id)
        ),
        produits_crees=await _count(
            session, select(Catalogue).where(Catalogue.id_utilisateur == utilisateur_id)
        ),
    )


async def get_utilisateur_detail(
    session: AsyncSession, utilisateur_id: int
) -> UtilisateurAdminDetail:
    """Détail d'un utilisateur : rattachements et volumétrie des données créées."""
    utilisateur = await _get_utilisateur_or_404(session, utilisateur_id)
    if utilisateur.id is None:  # pragma: no cover - garanti par la persistance
        raise HTTPException(status_code=500, detail="ID utilisateur manquant.")

    rattachements = (
        await _rattachements_par_utilisateur(session, [utilisateur.id])
    ).get(utilisateur.id, [])

    return UtilisateurAdminDetail(
        id=utilisateur.id,
        nom=utilisateur.nom,
        prenom=utilisateur.prenom,
        email=utilisateur.email,
        telephone=utilisateur.telephone,
        est_actif=utilisateur.est_actif,
        admin_plateforme=utilisateur.admin_plateforme,
        compte_protege=utilisateur.compte_protege,
        date_creation=utilisateur.date_creation,
        date_derniere_connexion=utilisateur.date_derniere_connexion,
        entreprises=rattachements,
        compteurs=await compteurs_utilisateur(session, utilisateur.id),
    )


# ---------------------------------------------------------------------------
# Modification : entreprise
# ---------------------------------------------------------------------------


async def update_entreprise(
    session: AsyncSession, entreprise_id: int, payload: EntrepriseAdminUpdate
) -> Entreprise:
    """
    Modifie l'identité légale d'une entreprise (raison sociale, SIRET, forme
    juridique) depuis l'administration de plateforme.

    **La correction ne vaut que pour l'avenir.** Les factures déjà émises
    conservent leur instantané figé de l'émetteur (`facture.siret_emetteur`,
    `snapshot_client`) : corriger le SIRET ici ne les réécrit jamais, et ne doit
    pas les réécrire — une facture porte le SIRET qui était en vigueur au jour
    de son émission. Seules les factures créées ensuite reprendront la valeur
    corrigée.

    Un SIRET déjà rattaché à une autre entreprise renvoie 409 (pré-vérification
    déterministe, doublée d'un filet `IntegrityError` contre la course). Une
    forme juridique inconnue ou inactive renvoie 422.
    """
    entreprise = await _get_entreprise_or_404(session, entreprise_id)
    donnees = payload.model_dump(exclude_unset=True)

    nouveau_siret = donnees.get("siret")
    if "siret" in donnees and nouveau_siret != entreprise.siret:
        await _verifier_siret_libre(session, nouveau_siret, entreprise_id)

    id_forme = donnees.get("id_forme_juridique")
    if "id_forme_juridique" in donnees and id_forme is not None:
        await _verifier_forme_juridique(session, id_forme)

    for champ, valeur in donnees.items():
        setattr(entreprise, champ, valeur)

    session.add(entreprise)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise conflict_from_integrity_error(exc, _SIRET_CONFLICTS) from None

    await session.refresh(entreprise)
    return entreprise


async def _verifier_siret_libre(
    session: AsyncSession, siret: str | None, entreprise_id: int
) -> None:
    """Refuse (409) un SIRET déjà porté par une *autre* entreprise."""
    if siret is None:
        return
    result = await session.exec(
        select(Entreprise)
        .where(Entreprise.siret == siret)
        .where(col(Entreprise.id) != entreprise_id)
    )
    if result.first() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ce SIRET est déjà rattaché à une autre entreprise.",
        )


async def _verifier_forme_juridique(
    session: AsyncSession, id_forme_juridique: int
) -> None:
    """Refuse (422) une forme juridique inconnue ou désactivée."""
    result = await session.exec(
        select(RefFormeJuridique)
        .where(RefFormeJuridique.id == id_forme_juridique)
        .where(col(RefFormeJuridique.est_actif).is_(True))
    )
    if result.first() is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="La forme juridique indiquée est introuvable ou inactive.",
        )


# ---------------------------------------------------------------------------
# Suspension / réactivation d'une entreprise
# ---------------------------------------------------------------------------


async def suspendre_entreprise(
    session: AsyncSession, entreprise_id: int, motif: str | None = None
) -> Entreprise:
    """
    Suspend une entreprise : coupe l'accès de tous ses membres et bascule sa
    souscription courante en `SUSPENDU`, en une seule transaction.

    L'accès est coupé par `Entreprise.est_actif`, contrôlé dans
    `verify_tenant_access` : les membres reçoivent un 403 sur toutes les routes
    tenant. Les routes hors tenant (`/utilisateurs/me`, `/abonnements/me`)
    continuent de répondre pour que le client puisse expliquer la situation.

    Aucune donnée n'est touchée : l'opération est intégralement réversible par
    `reactiver_entreprise`. Suspendre une entreprise déjà suspendue met
    seulement à jour le motif et la date.
    """
    entreprise = await _get_entreprise_or_404(session, entreprise_id)

    entreprise.est_actif = False
    entreprise.date_suspension = datetime.now(UTC)
    entreprise.motif_suspension = motif
    session.add(entreprise)

    souscription = await _souscription_courante(session, entreprise_id)
    if souscription is not None and souscription.statut == StatutSouscription.ACTIF:
        souscription.statut = StatutSouscription.SUSPENDU
        session.add(souscription)

    await session.commit()
    await session.refresh(entreprise)
    return entreprise


async def reactiver_entreprise(session: AsyncSession, entreprise_id: int) -> Entreprise:
    """
    Rétablit l'accès d'une entreprise suspendue et lui restitue un abonnement
    actif, en une seule transaction.

    La souscription courante est réactivée si elle était suspendue. Si elle a
    été résiliée — ou si l'entreprise n'en a aucune — une nouvelle souscription
    au plan gratuit est ouverte : une entreprise en service doit toujours avoir
    un abonnement actif. La trace de suspension (date, motif) est effacée.
    """
    entreprise = await _get_entreprise_or_404(session, entreprise_id)

    entreprise.est_actif = True
    entreprise.date_suspension = None
    entreprise.motif_suspension = None
    session.add(entreprise)

    souscription = await _souscription_courante(session, entreprise_id)
    if souscription is not None and souscription.statut == StatutSouscription.SUSPENDU:
        souscription.statut = StatutSouscription.ACTIF
        session.add(souscription)
    elif souscription is None or souscription.statut in (
        StatutSouscription.ANNULE,
        StatutSouscription.EXPIRE,
    ):
        plan_gratuit = await abonnements_services.resoudre_plan_gratuit(session)
        session.add(
            EntrepriseAbonnement(
                id_entreprise=entreprise_id,
                id_abonnement=plan_gratuit.id,
                date_debut=date.today(),
                date_fin=None,
                statut=StatutSouscription.ACTIF,
            )
        )

    await session.commit()
    await session.refresh(entreprise)
    return entreprise


async def _souscription_courante(
    session: AsyncSession, entreprise_id: int
) -> EntrepriseAbonnement | None:
    """
    Souscription la plus récente d'une entreprise, quel que soit son statut.

    Distinct de `_get_souscription_active` du module abonnements, qui ne
    considère que les souscriptions `ACTIF` : ici on veut aussi pouvoir agir sur
    une souscription suspendue ou résiliée. Même définition de « courante » que
    partout dans ce module : le plus grand identifiant.
    """
    statement = (
        select(EntrepriseAbonnement)
        .where(EntrepriseAbonnement.id_entreprise == entreprise_id)
        .order_by(col(EntrepriseAbonnement.id).desc())
    )
    return (await session.exec(statement)).first()


# ---------------------------------------------------------------------------
# Abonnement d'une entreprise ciblée
# ---------------------------------------------------------------------------


async def changer_plan(
    session: AsyncSession, entreprise_id: int, id_abonnement: int
) -> EntrepriseAbonnement:
    """
    Change le plan d'une entreprise ciblée par son id.

    Réutilise tel quel le service métier `abonnements.services.change_plan`
    (clôture de la souscription courante, création de la nouvelle, historique
    préservé) : la seule différence avec la voie utilisateur est l'origine de
    `entreprise_id` — un paramètre d'URL ici, le header tenant là-bas.
    """
    await _get_entreprise_or_404(session, entreprise_id)
    return await abonnements_services.change_plan(session, entreprise_id, id_abonnement)


async def prolonger_abonnement(
    session: AsyncSession, entreprise_id: int
) -> EntrepriseAbonnement:
    """
    Prolonge d'un mois l'abonnement payant d'une entreprise ciblée par son id.
    Réutilise tel quel `abonnements.services.prolonger_abonnement`.
    """
    await _get_entreprise_or_404(session, entreprise_id)
    return await abonnements_services.prolonger_abonnement(session, entreprise_id)


async def resilier_abonnement(
    session: AsyncSession, entreprise_id: int, motif: str | None = None
) -> EntrepriseAbonnement:
    """
    Résilie l'abonnement d'une entreprise : la souscription courante passe en
    `ANNULE` et l'accès est coupé, en une seule transaction.

    Différence avec la suspension : la suspension est une mesure temporaire dont
    on attend la levée, la résiliation clôt la relation commerciale. Les deux
    coupent l'accès et aucune ne touche aux données. `reactiver_entreprise`
    rouvre le service en ouvrant une nouvelle souscription au plan gratuit.
    """
    await _get_entreprise_or_404(session, entreprise_id)
    souscription = await _souscription_courante(session, entreprise_id)
    if souscription is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Cette entreprise n'a aucune souscription à résilier.",
        )
    if souscription.statut == StatutSouscription.ANNULE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cette souscription est déjà résiliée.",
        )

    souscription.statut = StatutSouscription.ANNULE
    souscription.date_fin = date.today()
    session.add(souscription)

    entreprise = await _get_entreprise_or_404(session, entreprise_id)
    entreprise.est_actif = False
    entreprise.date_suspension = datetime.now(UTC)
    entreprise.motif_suspension = motif or "Abonnement résilié."
    session.add(entreprise)

    await session.commit()
    await session.refresh(souscription)
    return souscription


# ---------------------------------------------------------------------------
# Désactivation / suppression : utilisateur
# ---------------------------------------------------------------------------


async def definir_activite_utilisateur(
    session: AsyncSession,
    utilisateur_id: int,
    actif: bool,
    current_admin: Utilisateur,
) -> Utilisateur:
    """
    Active ou désactive un compte utilisateur — la voie recommandée, réversible
    et sans perte de données.

    La désactivation est un coupe-circuit immédiat : `get_current_user` refuse
    déjà tout compte inactif, quel que soit le jeton présenté. Un administrateur
    ne peut pas se désactiver lui-même, et un compte protégé reste intouchable.

    La réactivation n'est **pas** soumise à la limite d'utilisateurs du plan :
    l'administrateur de plateforme agit en support et arbitre en connaissance de
    cause. Cette limite (`ensure_can_add_active_user`) continue de s'appliquer
    intégralement aux utilisateurs normaux.
    """
    utilisateur = await _get_utilisateur_or_404(session, utilisateur_id)

    if not actif:
        if utilisateur.id == current_admin.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Vous ne pouvez pas désactiver votre propre compte.",
            )
        if utilisateur.compte_protege:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Ce compte est protégé et ne peut pas être désactivé.",
            )

    utilisateur.est_actif = actif
    session.add(utilisateur)
    await session.commit()
    await session.refresh(utilisateur)
    return utilisateur


async def _entreprises_dont_il_est_seul_admin(
    session: AsyncSession, utilisateur_id: int
) -> list[str]:
    """
    Entreprises que cet utilisateur administre seul alors qu'elles comptent
    d'autres membres.

    Les supprimer laisserait une entreprise peuplée sans personne pour
    l'administrer. Une entreprise dont il est l'unique membre n'est pas
    concernée : elle devient simplement orpheline, ce qui est un état géré (un
    compte sans entreprise existe déjà à l'inscription).
    """
    liens = (
        await session.exec(
            select(UtilisateurEntreprise).where(
                UtilisateurEntreprise.id_utilisateur == utilisateur_id
            )
        )
    ).all()

    bloquantes: list[str] = []
    for lien in liens:
        if not lien.est_admin:
            continue
        membres = (
            await session.exec(
                select(UtilisateurEntreprise).where(
                    UtilisateurEntreprise.id_entreprise == lien.id_entreprise
                )
            )
        ).all()
        if len(membres) <= 1:
            continue
        autres_admins = [
            m for m in membres if m.est_admin and m.id_utilisateur != utilisateur_id
        ]
        if autres_admins:
            continue
        entreprise = await session.get(Entreprise, lien.id_entreprise)
        bloquantes.append(
            entreprise.nom_entreprise
            if entreprise is not None
            else f"entreprise #{lien.id_entreprise}"
        )
    return bloquantes


async def supprimer_utilisateur(
    session: AsyncSession, utilisateur_id: int, current_admin: Utilisateur
) -> None:
    """
    Supprime physiquement un compte utilisateur — opération de dernier recours.

    Cinq garde-fous, évalués dans cet ordre :

    1. compte protégé (racine) -> 403 ;
    2. l'administrateur lui-même -> 403 (pas d'auto-suppression) ;
    3. dernier administrateur de plateforme -> 409 ;
    4. seul administrateur d'une entreprise qui compte d'autres membres -> 409,
       il faut d'abord transférer l'administration ;
    5. a créé des données (facture, paiement, client, document, produit) -> 409
       orientant vers la désactivation. Ces lignes portent une responsabilité
       nominative — savoir qui a émis une facture fait partie de la piste
       d'audit comptable — et sont référencées en base sans cascade.

    En pratique, seuls des comptes créés puis jamais utilisés franchissent ces
    cinq contrôles. Les rattachements (`utilisateur_entreprise`,
    `utilisateur_role`) et les jetons de réinitialisation partent en cascade ;
    les traces d'audit et les notifications sont détachées plutôt que
    supprimées.
    """
    utilisateur = await _get_utilisateur_or_404(session, utilisateur_id)

    if utilisateur.compte_protege:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Ce compte est protégé et ne peut pas être supprimé.",
        )

    if utilisateur.id == current_admin.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Vous ne pouvez pas supprimer votre propre compte.",
        )

    if utilisateur.admin_plateforme:
        total_admins = await _count(
            session,
            select(Utilisateur).where(col(Utilisateur.admin_plateforme).is_(True)),
        )
        if total_admins <= 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Impossible de supprimer le dernier administrateur de la "
                    "plateforme."
                ),
            )

    bloquantes = await _entreprises_dont_il_est_seul_admin(session, utilisateur_id)
    if bloquantes:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Cet utilisateur administre seul : "
                f"{', '.join(bloquantes)}. Transférez l'administration à un "
                "autre membre avant de supprimer le compte."
            ),
        )

    compteurs = await compteurs_utilisateur(session, utilisateur_id)
    if any(compteurs.model_dump().values()):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Cet utilisateur a créé des données comptables "
                f"({compteurs.factures_creees} facture(s), "
                f"{compteurs.clients_crees} client(s), "
                f"{compteurs.documents_charges} document(s)) qui doivent rester "
                "rattachées à leur auteur. Désactivez le compte plutôt que de "
                "le supprimer."
            ),
        )

    # Traces conservées mais détachées : le journal d'audit et les notifications
    # ont un auteur nullable, on ne détruit pas l'historique de la plateforme.
    await session.execute(
        update(JournalAudit)
        .where(col(JournalAudit.id_utilisateur) == utilisateur_id)
        .values(id_utilisateur=None)
    )
    await session.execute(
        delete(Notification).where(col(Notification.id_utilisateur) == utilisateur_id)
    )

    await session.delete(utilisateur)
    await session.commit()


# ---------------------------------------------------------------------------
# Suppression : entreprise
# ---------------------------------------------------------------------------


async def supprimer_entreprise(session: AsyncSession, entreprise_id: int) -> None:
    """
    Supprime physiquement une entreprise — uniquement si elle est vierge.

    Deux barrières, dans cet ordre :

    1. **Au moins une facture scellée (sortie de l'état brouillon) -> 403
       définitif.** Aucun paramètre ne permet de passer outre : l'inaltérabilité
       et l'obligation de conservation (six ans au titre du CGI, dix au titre du
       Code de commerce) rendent cette suppression illégale, pas seulement
       risquée. La suspension est la seule réponse possible. Si le référentiel
       des statuts est inexploitable, toutes les factures sont réputées scellées.
    2. **Toute autre donnée (facture brouillon, client, document, produit) ->
       409**, listant ce qui bloque.

    Ne franchissent ces barrières que les entreprises réellement vides :
    doublon, compte de test, inscription abandonnée. Sont alors supprimés les
    rattachements et les souscriptions ; les utilisateurs eux-mêmes ne le sont
    **jamais** (ils peuvent appartenir à d'autres entreprises et un compte sans
    entreprise est un état géré). Les traces d'audit sont détachées.
    """
    await _get_entreprise_or_404(session, entreprise_id)
    compteurs = await compteurs_entreprise(session, entreprise_id)

    if compteurs.factures_scellees > 0:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Cette entreprise porte {compteurs.factures_scellees} facture(s) "
                "émise(s), soumises à l'obligation de conservation et à "
                "l'inaltérabilité : elle ne peut pas être supprimée. Suspendez-la "
                "à la place."
            ),
        )

    bloquants = {
        "facture(s) brouillon": compteurs.factures_brouillon,
        "client(s)": compteurs.clients,
        "document(s)": compteurs.documents,
        "produit(s)": compteurs.produits,
    }
    details = [f"{nombre} {libelle}" for libelle, nombre in bloquants.items() if nombre]
    if details:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cette entreprise contient encore des données ({', '.join(details)}). "
                "Supprimez-les d'abord, ou suspendez l'entreprise."
            ),
        )

    # Traces conservées mais détachées (id_entreprise nullable).
    await session.execute(
        update(JournalAudit)
        .where(col(JournalAudit.id_entreprise) == entreprise_id)
        .values(id_entreprise=None)
    )
    await session.execute(
        delete(Notification).where(col(Notification.id_entreprise) == entreprise_id)
    )
    # Rattachements et souscriptions : les comptes utilisateurs survivent.
    await session.execute(
        delete(UtilisateurRole).where(
            col(UtilisateurRole.id_entreprise) == entreprise_id
        )
    )
    await session.execute(
        delete(UtilisateurEntreprise).where(
            col(UtilisateurEntreprise.id_entreprise) == entreprise_id
        )
    )
    await session.execute(
        delete(EntrepriseAbonnement).where(
            col(EntrepriseAbonnement.id_entreprise) == entreprise_id
        )
    )
    await session.execute(delete(Entreprise).where(col(Entreprise.id) == entreprise_id))

    try:
        await session.commit()
    except IntegrityError:
        # Filet contre une donnée créée entre la vérification et le commit : la
        # base refuse alors la suppression (aucune FK vers `entreprise` n'est en
        # cascade), on préfère un 409 explicite à un 500.
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Des données ont été créées pour cette entreprise pendant la "
                "suppression. Réessayez ou suspendez-la."
            ),
        ) from None
