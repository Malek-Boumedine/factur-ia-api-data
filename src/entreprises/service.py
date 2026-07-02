"""
Logique métier du module entreprises.

L'onboarding crée une NOUVELLE entreprise et y rattache l'utilisateur courant
comme propriétaire, dans une transaction atomique : entreprise + pivot
propriétaire + rôle PROPRIETAIRE + souscription au plan gratuit sont validés
ensemble, ou rien n'est persisté.
"""

from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.abonnements.models import (
    Abonnement,
    EntrepriseAbonnement,
    StatutSouscription,
)
from src.auth.models import Role, UtilisateurRole
from src.entreprises.exceptions import (
    ConfigurationManquanteError,
    FormeJuridiqueIntrouvableError,
    SiretDejaUtiliseError,
)
from src.entreprises.models import (
    Entreprise,
    RefFormeJuridique,
    UtilisateurEntreprise,
)
from src.entreprises.schemas import EntrepriseCreate
from src.utilisateurs.models import Utilisateur

# Libellés des données de référence (seed) résolues au runtime.
_OWNER_ROLE_LIBELLE = "PROPRIETAIRE"
_FREE_PLAN_LIBELLE = "GRATUITE"


async def create_entreprise(
    session: AsyncSession,
    current_user: Utilisateur,
    data: EntrepriseCreate,
) -> Entreprise:
    """
    Crée une entreprise et fait de l'utilisateur courant son propriétaire.

    Étapes (transaction unique) :
    1. l'entreprise ;
    2. le rattachement propriétaire (`UtilisateurEntreprise`, `est_admin=True`) ;
    3. le rôle métier `PROPRIETAIRE` (`UtilisateurRole`, contextualisé à
       l'entreprise) ;
    4. la souscription au plan gratuit (`EntrepriseAbonnement`, statut `ACTIF`).

    Le propriétaire est **toujours** l'utilisateur authentifié (`current_user`),
    jamais une valeur issue de la requête.
    """
    await _verifier_siret_disponible(session, data.siret)
    await _verifier_forme_juridique(session, data.id_forme_juridique)

    owner_role = await _resoudre_role_proprietaire(session)
    free_plan = await _resoudre_plan_gratuit(session)

    try:
        entreprise = Entreprise(
            nom_entreprise=data.nom_entreprise,
            siret=data.siret,
            id_forme_juridique=data.id_forme_juridique,
        )
        session.add(entreprise)
        # flush pour obtenir l'id auto-généré avant de créer les liaisons
        await session.flush()

        session.add(
            UtilisateurEntreprise(
                id_utilisateur=current_user.id,
                id_entreprise=entreprise.id,
                est_admin=True,
            )
        )
        session.add(
            UtilisateurRole(
                id_utilisateur=current_user.id,
                id_role=owner_role.id,
                id_entreprise=entreprise.id,
            )
        )
        session.add(
            EntrepriseAbonnement(
                id_entreprise=entreprise.id,
                id_abonnement=free_plan.id,
                statut=StatutSouscription.ACTIF,
            )
        )

        await session.commit()
    except IntegrityError as exc:
        # Filet de sécurité contre une collision de SIRET concurrente
        # (la contrainte d'unicité en base est le garde-fou final).
        await session.rollback()
        raise SiretDejaUtiliseError(
            "Ce SIRET est déjà rattaché à une entreprise."
        ) from exc
    except Exception:
        await session.rollback()
        raise

    await session.refresh(entreprise)
    return entreprise


async def _verifier_siret_disponible(session: AsyncSession, siret: str | None) -> None:
    """Rejette la création si le SIRET est déjà utilisé."""
    if siret is None:
        return
    result = await session.exec(select(Entreprise).where(Entreprise.siret == siret))
    if result.first() is not None:
        raise SiretDejaUtiliseError("Ce SIRET est déjà rattaché à une entreprise.")


async def _verifier_forme_juridique(
    session: AsyncSession, id_forme_juridique: int | None
) -> None:
    """Vérifie que la forme juridique référencée existe et est active."""
    if id_forme_juridique is None:
        return
    result = await session.exec(
        select(RefFormeJuridique).where(
            RefFormeJuridique.id == id_forme_juridique,
            col(RefFormeJuridique.est_actif).is_(True),
        )
    )
    if result.first() is None:
        raise FormeJuridiqueIntrouvableError(
            "La forme juridique indiquée est introuvable ou inactive."
        )


async def _resoudre_role_proprietaire(session: AsyncSession) -> Role:
    """Retourne le rôle PROPRIETAIRE (seedé) ou lève une erreur de config."""
    result = await session.exec(select(Role).where(Role.libelle == _OWNER_ROLE_LIBELLE))
    role = result.first()
    if role is None:
        raise ConfigurationManquanteError(
            f"Rôle '{_OWNER_ROLE_LIBELLE}' absent : le seed n'a pas été exécuté."
        )
    return role


async def _resoudre_plan_gratuit(session: AsyncSession) -> Abonnement:
    """Retourne le plan d'abonnement gratuit (seedé) ou lève une erreur."""
    result = await session.exec(
        select(Abonnement).where(Abonnement.libelle == _FREE_PLAN_LIBELLE)
    )
    plan = result.first()
    if plan is None:
        raise ConfigurationManquanteError(
            f"Plan '{_FREE_PLAN_LIBELLE}' absent : le seed n'a pas été exécuté."
        )
    return plan
