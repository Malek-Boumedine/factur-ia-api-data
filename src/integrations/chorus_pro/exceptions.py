"""Exceptions de l'intégration Chorus Pro (PISTE).

Hiérarchie volontairement plate : le routeur les traduit en réponses HTTP
(503 configuration absente, 502 échec amont) sans exposer de détail interne.
"""


class ChorusProError(Exception):
    """Erreur générique lors d'un échange avec Chorus Pro (réseau, HTTP)."""


class ChorusProConfigurationError(ChorusProError):
    """Les credentials PISTE ou le compte technique ne sont pas configurés."""


class ChorusProAuthError(ChorusProError):
    """Échec d'obtention du token OAuth2 auprès de PISTE."""


class ChorusProDepotError(ChorusProError):
    """Rejet métier du dépôt par Chorus Pro : ``codeRetour != 0`` dans une
    réponse HTTP 200. Le ``libelle`` renvoyé par Chorus Pro explique le rejet.
    """

    def __init__(self, code_retour: int, libelle: str) -> None:
        self.code_retour = code_retour
        self.libelle = libelle
        super().__init__(
            f"Dépôt refusé par Chorus Pro (codeRetour={code_retour}) : {libelle}"
        )
