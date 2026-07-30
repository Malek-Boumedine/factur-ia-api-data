class FacturXError(Exception):
    """Erreur générique lors de la génération d'un fichier Factur-X."""


class DonneesFacturXManquantesError(FacturXError):
    """La facture n'est pas conforme au profil MINIMUM : donnée obligatoire
    absente ou incohérente (règles de ``conformite.check_facturx_minimum``).

    Ne devrait pas arriver sur une facture validée (les snapshots sont
    figés à la validation), mais reste possible si l'entreprise n'avait
    pas de SIRET au moment de la validation.
    """
