class DocumentError(Exception):
    """Classe de base pour les erreurs du module documents."""

    pass


class DocumentIntrouvableError(DocumentError):
    """Levée quand le document ciblé par le callback OCR n'existe pas."""

    pass


class DocumentLieAFactureError(DocumentError):
    """Levée quand une facture (brouillon ou validée) référence le document.

    La suppression est refusée : la facture doit être supprimée d'abord
    (une facture validée, immuable, ne le sera jamais — le document est
    alors conservé comme trace documentaire pour l'audit comptable).
    """

    pass
