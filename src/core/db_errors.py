"""
Conversion des erreurs d'intégrité base de données en réponses HTTP claires.

Centralise le mapping d'une `IntegrityError` (violation de contrainte unique)
vers une `HTTPException` 409, avec un message rattaché au champ en conflit. Le
message d'erreur SQL (ex : MySQL « Duplicate entry ... for key
'client.ix_client_siret' ») est inspecté pour identifier la contrainte violée.
"""

from collections.abc import Sequence

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError


class UniqueConflict:
    """Associe un fragment de clé/contrainte SQL à un message utilisateur."""

    def __init__(self, marker: str, detail: str) -> None:
        # Fragment attendu dans le message d'erreur SQL (nom de clé ou colonne).
        self.marker = marker
        # Message renvoyé au client, nommant le champ en conflit.
        self.detail = detail


def conflict_from_integrity_error(
    exc: IntegrityError,
    conflicts: Sequence[UniqueConflict],
    default_detail: str = "Conflit : une valeur déjà utilisée existe en base.",
) -> HTTPException:
    """
    Construit une `HTTPException` 409 à partir d'une `IntegrityError`.

    Parcourt `conflicts` dans l'ordre et renvoie le premier dont le `marker`
    apparaît dans le message d'erreur SQL. À défaut (contrainte non anticipée),
    renvoie un 409 générique plutôt qu'un 500. Le rollback de session reste à
    la charge de l'appelant.
    """
    message = str(getattr(exc, "orig", None) or exc).lower()
    for conflict in conflicts:
        if conflict.marker.lower() in message:
            return HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail=conflict.detail
            )
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=default_detail)
