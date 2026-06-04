import difflib
from typing import Any


def calculer_similarite(chaine1: str | None, chaine2: str | None) -> float:
    """Calcule un ratio de similarité entre 0 et 1 pour deux chaînes."""
    if not chaine1 or not chaine2:
        return 0.0
    # tout en minuscules pour comparer
    return difflib.SequenceMatcher(None, chaine1.lower(), chaine2.lower()).ratio()


def reconcilier_donnees_ocr_api(
    ocr_data: dict[str, Any], api_results: list[dict[str, Any]]
) -> dict[str, Any]:
    """
    Croise les données lues par l'OCR avec
    la liste de résultats de l'API Gouvernementale.
    Gère les cas de match unique, multiple, ou d'échec.
    """
    # 1. pas de résultat API : on garde ce que l'OCR a lu (fallback)
    if not api_results:
        return {
            "statut": "ocr_seul",
            "donnees_pre_remplies": ocr_data,
            "alternatives": [],
        }

    # 2. un seul résultat API (ex: recherche par SIRET exact) :
    # C'est la source de vérité
    if len(api_results) == 1:
        return {
            "statut": "match_parfait",
            "donnees_pre_remplies": api_results[0],
            "alternatives": [],
        }

    # 3. plusieurs résultats API : Le front-end devra choisir
    # On va calculer un score de confiance
    # basé sur la ressemblance de l'adresse
    adresse_ocr = ocr_data.get("adresse", "")

    for api_client in api_results:
        # On calcule à quel point l'adresse de
        # l'API ressemble à l'adresse lue sur le PDF
        score = calculer_similarite(adresse_ocr, api_client.get("adresse", ""))
        api_client["score_confiance"] = round(score * 100, 2)
    resultats_tries = sorted(
        api_results, key=lambda x: x.get("score_confiance", 0), reverse=True
    )

    return {
        "statut": "ambiguite",
        # pré-remplit le formulaire avec le résultat au meilleur score
        "donnees_pre_remplies": resultats_tries[0],
        # on envoie toute la liste au front pour
        # afficher la modale "Avez-vous voulu dire ?"
        "alternatives": resultats_tries,
    }
