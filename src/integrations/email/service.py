"""
Abstraction minimale d'envoi d'email.

Aucun fournisseur SMTP n'est câblé pour le MVP : l'implémentation par défaut
(`ConsoleEmailSender`) se contente de journaliser le contenu (dont le lien de
réinitialisation). Pour brancher un vrai fournisseur plus tard, il suffit
d'ajouter une implémentation du `Protocol` `EmailSender` et de l'exposer via
`get_email_sender` — le code métier reste inchangé.
"""

from typing import Protocol, runtime_checkable

from loguru import logger

from src.core.config import settings


@runtime_checkable
class EmailSender(Protocol):
    """Contrat d'envoi d'un email transactionnel."""

    async def send(self, recipient: str, subject: str, body: str) -> None:
        """Envoie un email au format texte à un destinataire unique."""
        ...


class ConsoleEmailSender:
    """
    Implémentation de développement : journalise l'email au lieu de l'envoyer.

    Permet de récupérer le lien de réinitialisation dans les logs sans
    dépendre d'un serveur SMTP.
    """

    async def send(self, recipient: str, subject: str, body: str) -> None:
        """Journalise l'email qui aurait été envoyé."""
        logger.info(
            "[EMAIL] expéditeur={} destinataire={} sujet={!r}\n{}",
            settings.EMAIL_SENDER,
            recipient,
            subject,
            body,
        )


def get_email_sender() -> EmailSender:
    """
    Dépendance FastAPI : retourne l'implémentation d'envoi d'email active.

    Point d'extension unique pour basculer vers un fournisseur SMTP réel
    (sélection par `settings.ENVIRONNEMENT` par exemple) sans toucher aux
    routers ni aux services.
    """
    return ConsoleEmailSender()


def build_reset_link(plain_token: str) -> str:
    """Construit l'URL de réinitialisation à destination du front (BFF Django)."""
    base = settings.FRONTEND_RESET_URL.rstrip("/")
    return f"{base}?token={plain_token}"


def build_reset_email(plain_token: str) -> tuple[str, str]:
    """
    Prépare le sujet et le corps de l'email de réinitialisation.

    Retourne le couple ``(subject, body)``.
    """
    link = build_reset_link(plain_token)
    subject = "Réinitialisation de votre mot de passe"
    body = (
        "Bonjour,\n\n"
        "Vous avez demandé la réinitialisation de votre mot de passe. "
        "Cliquez sur le lien ci-dessous pour définir un nouveau mot de passe :\n\n"
        f"{link}\n\n"
        f"Ce lien est valable {settings.RESET_TOKEN_EXPIRE_HOURS} heure(s) et ne "
        "peut être utilisé qu'une seule fois.\n\n"
        "Si vous n'êtes pas à l'origine de cette demande, ignorez cet email : "
        "votre mot de passe restera inchangé.\n"
    )
    return subject, body
