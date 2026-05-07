class FacturationError(Exception):
    """Classe de base pour les erreurs du module facturation."""

    pass


class StatutNonConfigureError(FacturationError):
    """Levée quand un statut requis n'existe pas en base."""

    pass


class TauxTvaIntrouvableError(FacturationError):
    """Levée quand un ID de taux de TVA fourni par le client n'existe pas."""

    pass
