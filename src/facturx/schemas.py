"""Schémas du rapport de conformité Factur-X (profil MINIMUM).

Le rapport est destiné à l'affichage côté client : ``code`` est un identifiant
stable machine-exploitable, ``message`` un texte en français affichable tel
quel, ``champ`` le champ de la facture concerné.
"""

from pydantic import BaseModel


class ProblemeConformiteFacturX(BaseModel):
    """Un problème de conformité détecté sur la facture.

    Chaque ``code`` a une sévérité fixe (toujours erreur, ou toujours
    avertissement), à une exception près : ``seller_siret_luhn_invalid`` et
    ``buyer_siret_luhn_invalid`` apparaissent dans ``erreurs`` quand le
    serveur applique strictement la clé de Luhn (``SIRET_LUHN_STRICT=True``,
    défaut et obligation en production), mais dans ``avertissements`` quand
    le contrôle est relâché (sandbox Chorus Pro, dont les SIRET fictifs ne
    respectent pas la clé). Le client doit donc traiter ces deux codes dans
    les deux listes.
    """

    champ: str
    code: str
    message: str


class RapportConformiteFacturX(BaseModel):
    """Rapport de conformité au profil MINIMUM, sans génération de fichier.

    ``conforme`` est vrai si aucune erreur bloquante n'est détectée ; les
    avertissements sont informatifs et n'empêchent pas la transmission.
    """

    conforme: bool
    erreurs: list[ProblemeConformiteFacturX]
    avertissements: list[ProblemeConformiteFacturX]
