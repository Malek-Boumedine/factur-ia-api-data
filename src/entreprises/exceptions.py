class EntrepriseError(Exception):
    """Classe de base pour les erreurs du module entreprises."""

    pass


class SiretDejaUtiliseError(EntrepriseError):
    """Levée quand le SIRET fourni est déjà rattaché à une entreprise."""

    pass


class FormeJuridiqueIntrouvableError(EntrepriseError):
    """Levée quand la forme juridique référencée n'existe pas ou est inactive."""

    pass


class ConfigurationManquanteError(EntrepriseError):
    """Levée quand une donnée de référence requise (rôle propriétaire, plan
    gratuit) est absente de la base — le seed n'a pas été exécuté."""

    pass
