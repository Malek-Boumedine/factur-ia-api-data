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
    """Levée quand on tente de valider ou modifier une facture \
        qui n'est pas un brouillon."""

    pass


class FactureIncompleteError(FacturationError):
    """Levée quand on tente de valider un brouillon incomplet (ex: sans client)."""

    pass


class TypeFactureNonModifiableError(FacturationError):
    """Levée quand on tente de changer le type d'un avoir \
        lié à une facture d'origine."""

    pass


class NumerotationConcurrenceError(FacturationError):
    """Levée quand l'attribution du numéro définitif échoue après plusieurs \
        tentatives à cause de validations simultanées dans la même entreprise."""

    pass
