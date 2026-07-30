class FacturXError(Exception):
    """Erreur générique lors de la génération d'un fichier Factur-X."""


class DonneesFacturXManquantesError(FacturXError):
    """Une donnée obligatoire du XML CII est absente de la facture.

    Ne devrait pas arriver sur une facture validée (les snapshots sont
    figés à la validation), mais reste possible si l'entreprise n'avait
    pas de SIRET au moment de la validation.
    """
