class FacturationError(Exception):
    """Classe de base pour les erreurs du module facturation."""

    pass


class StatutNonConfigureError(FacturationError):
    """Levée quand un statut requis n'existe pas en base."""

    pass


class TauxTvaIntrouvableError(FacturationError):
    """Levée quand un ID de taux de TVA fourni par le client n'existe pas."""

    pass


class FactureNotFoundError(FacturationError):
    """Levée quand la facture n'existe pas ou n'appartient pas à l'entreprise."""

    pass


class TransitionStatutInvalideError(FacturationError):
    """Levée quand on tente de valider une facture qui n'est pas un brouillon."""

    pass
