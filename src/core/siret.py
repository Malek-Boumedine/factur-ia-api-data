"""Normalisation des SIRET/SIREN saisis ou collés.

Source de vérité unique pour tous les points d'entrée d'un SIRET/SIREN
(recherche SIRENE, fiches client et entreprise, brouillons de facture,
webhook OCR) : les formats d'affichage courants (``340 216 121 33798``,
``340.216.121.33798``, tirets, espaces insécables ou fines) sont acceptés
et ramenés à la forme canonique « chiffres seuls ».
"""

import re

# Séparateurs d'affichage courants : tout blanc Unicode (espace normale,
# insécable U+00A0, fine U+202F/U+2009...), point ou tiret.
_DISPLAY_SEPARATORS_RE = re.compile(r"[\s.\-]")


def normalize_siret_input(value: str) -> str:
    """Retire les séparateurs d'affichage d'un SIRET/SIREN.

    Ne fait que nettoyer : aucun contrôle de longueur ni de contenu,
    ceux-ci restent du ressort de chaque point d'entrée (permissif sur un
    brouillon, strict sur une fiche entreprise).
    """
    return _DISPLAY_SEPARATORS_RE.sub("", value)


def validate_siret_flexible(value: object) -> object:
    """Normalise un SIRET optionnel : chiffres uniquement, incomplet accepté.

    Pour un ``field_validator`` pydantic en mode ``before`` : les non-chaînes
    (dont ``None``) passent telles quelles, une chaîne vide ou réduite à des
    séparateurs vaut effacement (``None``). Un SIRET incomplet est accepté
    (état de travail) ; la contrainte ``max_length`` du champ s'applique
    ensuite sur la valeur nettoyée.
    """
    if not isinstance(value, str):
        return value
    cleaned = normalize_siret_input(value)
    if cleaned == "":
        return None
    if not cleaned.isdigit():
        raise ValueError("Le SIRET ne doit contenir que des chiffres.")
    return cleaned


def validate_siret_strict(value: object) -> object:
    """Normalise un SIRET optionnel et exige exactement 14 chiffres.

    Pour un ``field_validator`` pydantic en mode ``before`` (le nettoyage
    doit précéder les contraintes ``min_length``/``max_length`` du champ) :
    les non-chaînes (dont ``None``) passent telles quelles.
    """
    if not isinstance(value, str):
        return value
    cleaned = normalize_siret_input(value)
    if not cleaned.isdigit() or len(cleaned) != 14:
        raise ValueError("Le SIRET doit comporter exactement 14 chiffres.")
    return cleaned
