"""
Logique métier de la réinitialisation de mot de passe.

Le router reste mince : il délègue ici la génération/validation des tokens et
la mise à jour du hash. Toutes les réponses exposées au client sont neutres et
ne divulguent jamais l'existence (ou non) d'un compte.
"""

from datetime import UTC, datetime, timedelta

from sqlmodel import col, delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.auth.models import ReinitialisationMotDePasse
from src.core.config import settings
from src.core.security import (
    generate_reset_token,
    get_password_hash,
    hash_reset_token,
)
from src.integrations.email.service import (
    EmailSender,
    build_reset_email,
)
from src.utilisateurs.models import Utilisateur


async def request_password_reset(
    session: AsyncSession,
    email: str,
    email_sender: EmailSender,
) -> None:
    """
    Traite une demande « mot de passe oublié ».

    Si un compte actif correspond à l'email : invalide ses éventuels tokens en
    cours, en génère un nouveau (hashé en base) et envoie le lien par email.
    Sinon, ne fait rien. Dans tous les cas la fonction ne lève pas d'erreur :
    l'appelant renvoie une réponse identique pour ne pas divulguer l'existence
    du compte.
    """
    result = await session.exec(select(Utilisateur).where(Utilisateur.email == email))
    user = result.first()

    if user is None or not user.est_actif:
        return

    # Invalide les demandes précédentes non consommées de cet utilisateur
    # (un seul lien de réinitialisation valable à la fois).
    await session.exec(
        delete(ReinitialisationMotDePasse).where(
            col(ReinitialisationMotDePasse.id_utilisateur) == user.id,
            col(ReinitialisationMotDePasse.date_utilisation).is_(None),
        )
    )

    plain_token, token_hash = generate_reset_token()
    expiration = datetime.now(UTC) + timedelta(hours=settings.RESET_TOKEN_EXPIRE_HOURS)
    session.add(
        ReinitialisationMotDePasse(
            id_utilisateur=user.id,
            token_hash=token_hash,
            date_expiration=expiration,
        )
    )
    await session.commit()

    subject, body = build_reset_email(plain_token)
    await email_sender.send(user.email, subject, body)


async def apply_password_reset(
    session: AsyncSession,
    token: str,
    new_password: str,
) -> bool:
    """
    Applique un nouveau mot de passe à partir d'un token de réinitialisation.

    Valide le token (existence, non-expiré, non-utilisé), met à jour le hash du
    mot de passe puis marque le token comme consommé (usage unique).

    Retourne ``True`` si la réinitialisation a réussi, ``False`` si le token est
    invalide/expiré/déjà utilisé — sans distinguer la cause pour l'appelant.
    """
    token_hash = hash_reset_token(token)
    result = await session.exec(
        select(ReinitialisationMotDePasse).where(
            ReinitialisationMotDePasse.token_hash == token_hash
        )
    )
    reset_request = result.first()

    now = datetime.now(UTC)
    if (
        reset_request is None
        or reset_request.date_utilisation is not None
        or _is_expired(reset_request.date_expiration, now)
    ):
        return False

    user_result = await session.exec(
        select(Utilisateur).where(Utilisateur.id == reset_request.id_utilisateur)
    )
    user = user_result.first()
    if user is None or not user.est_actif:
        return False

    user.hash_mot_de_passe = get_password_hash(new_password)
    reset_request.date_utilisation = now
    session.add(user)
    session.add(reset_request)
    await session.commit()
    return True


def _is_expired(expiration_date: datetime, now: datetime) -> bool:
    """Compare l'expiration à l'instant courant en tolérant les datetimes naïfs.

    MySQL restitue les datetimes sans fuseau ; on les considère alors comme
    UTC pour une comparaison cohérente avec un instant `aware`.
    """
    if expiration_date.tzinfo is None:
        expiration_date = expiration_date.replace(tzinfo=UTC)
    return expiration_date < now
