class DocumentError(Exception):
    """Classe de base pour les erreurs du module documents."""

    pass


class DocumentIntrouvableError(DocumentError):
    """Levée quand le document ciblé par le callback OCR n'existe pas."""

    pass
