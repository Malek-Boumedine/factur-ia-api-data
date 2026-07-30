"""Règles de conformité métier d'une facture au profil Factur-X MINIMUM.

Source de vérité unique, partagée entre le rapport de conformité (route
dédiée, sans génération) et la construction du XML CII
(``build_cii_minimum_xml``) : présence des champs obligatoires du profil
MINIMUM, cohérence arithmétique des totaux, validité des SIRET (14 chiffres
et clé de Luhn). La validation structurelle du XML reste du ressort du XSD,
appliqué au moment de la génération (``check_xsd=True``).

Les erreurs bloquent la transmission (le fichier serait rejeté par la
plateforme de dématérialisation) ; les avertissements signalent les limites
connues des données sans empêcher l'envoi.
"""

import re
from decimal import Decimal

from src.entreprises.models import Entreprise
from src.factures.models import Facture, TypeFacture
from src.facturx.schemas import ProblemeConformiteFacturX, RapportConformiteFacturX

# Tolérance d'arrondi sur TTC = HT + TVA (montants stockés à 2 décimales).
TOLERANCE_ARRONDI = Decimal("0.01")
# SIREN de La Poste : seule exception officielle à la clé de Luhn du SIRET.
SIREN_LA_POSTE = "356000000"

_SIRET_RE = re.compile(r"\d{14}")
_DEVISE_RE = re.compile(r"[A-Z]{3}")


def _luhn_valid(digits: str) -> bool:
    """Contrôle la clé de Luhn d'une chaîne de chiffres."""
    total = 0
    for position, caractere in enumerate(reversed(digits)):
        chiffre = int(caractere)
        if position % 2 == 1:
            chiffre *= 2
            if chiffre > 9:
                chiffre -= 9
        total += chiffre
    return total % 10 == 0


def _siret_error(siret: str) -> str | None:
    """Renvoie la raison d'invalidité d'un SIRET, ou None s'il est valide."""
    if not _SIRET_RE.fullmatch(siret):
        return "doit comporter exactement 14 chiffres"
    if siret.startswith(SIREN_LA_POSTE):
        return None
    if not _luhn_valid(siret):
        return "clé de contrôle (Luhn) invalide"
    return None


def check_facturx_minimum(
    facture: Facture, entreprise: Entreprise
) -> RapportConformiteFacturX:
    """Vérifie qu'une facture validée est prête pour la transmission Factur-X.

    Fonction pure (aucune I/O) : elle ne lit que la facture (snapshots figés
    à la validation) et la fiche entreprise. Tous les problèmes sont
    collectés — pas d'arrêt au premier — pour un retour complet au client.
    """
    erreurs: list[ProblemeConformiteFacturX] = []
    avertissements: list[ProblemeConformiteFacturX] = []

    def erreur(champ: str, code: str, message: str) -> None:
        erreurs.append(
            ProblemeConformiteFacturX(champ=champ, code=code, message=message)
        )

    def avertissement(champ: str, code: str, message: str) -> None:
        avertissements.append(
            ProblemeConformiteFacturX(champ=champ, code=code, message=message)
        )

    # Numéro (BT-1) — non-nullable en base, filet de sécurité.
    if not facture.numero_facture.strip():
        erreur(
            "numero_facture",
            "invoice_number_missing",
            "Le numéro de facture est vide.",
        )

    # Devise (BT-5).
    if not _DEVISE_RE.fullmatch(facture.devise):
        erreur(
            "devise",
            "currency_invalid",
            f"Devise « {facture.devise} » invalide : code ISO 4217 à 3 lettres "
            "majuscules attendu (ex : EUR).",
        )

    # Nom du vendeur (BT-27) — lu sur la fiche entreprise courante.
    if not entreprise.nom_entreprise.strip():
        erreur(
            "nom_entreprise",
            "seller_name_missing",
            "Le nom de l'entreprise émettrice est vide.",
        )
    else:
        avertissement(
            "nom_entreprise",
            "seller_name_not_snapshotted",
            "Le nom de l'émetteur est lu sur la fiche entreprise courante, "
            "non figé à la validation : le fichier reflétera sa valeur actuelle.",
        )

    # SIRET du vendeur (BT-30, schéma ICD 0009) — obligatoire en France.
    if not facture.siret_emetteur:
        erreur(
            "siret_emetteur",
            "seller_siret_missing",
            "Le SIRET de l'émetteur n'a pas été figé à la validation.",
        )
    else:
        raison = _siret_error(facture.siret_emetteur)
        if raison is not None:
            erreur(
                "siret_emetteur",
                "seller_siret_invalid",
                f"SIRET émetteur « {facture.siret_emetteur} » invalide : {raison}.",
            )

    # Nom de l'acheteur (BT-44) — depuis le snapshot client figé.
    snapshot = facture.snapshot_client or {}
    raison_sociale = snapshot.get("raison_sociale")
    if not raison_sociale or not str(raison_sociale).strip():
        erreur(
            "snapshot_client.raison_sociale",
            "buyer_name_missing",
            "La raison sociale du destinataire est absente du snapshot client.",
        )

    # SIRET du destinataire (BT-47) — optionnel au profil MINIMUM, mais s'il
    # est présent il part dans le XML : il doit alors être valide.
    if not facture.siret_destinataire:
        avertissement(
            "siret_destinataire",
            "buyer_siret_missing",
            "Aucun SIRET destinataire : optionnel au profil MINIMUM, mais "
            "attendu pour une facture B2B en France.",
        )
    else:
        raison = _siret_error(facture.siret_destinataire)
        if raison is not None:
            erreur(
                "siret_destinataire",
                "buyer_siret_invalid",
                "SIRET destinataire "
                f"« {facture.siret_destinataire} » invalide : {raison}.",
            )

    # Cohérence arithmétique des totaux (BT-109, BT-110, BT-112).
    ecart = abs(facture.total_ttc - (facture.total_ht + facture.total_tva))
    if ecart > TOLERANCE_ARRONDI:
        erreur(
            "total_ttc",
            "totals_mismatch",
            f"Total TTC ({facture.total_ttc}) différent de total HT "
            f"({facture.total_ht}) + total TVA ({facture.total_tva}).",
        )

    # Signe des montants : un avoir est stocké en négatif, une facture en positif.
    totaux = (facture.total_ht, facture.total_tva, facture.total_ttc)
    if facture.type_facture == TypeFacture.AVOIR:
        if any(total > 0 for total in totaux):
            erreur(
                "total_ttc",
                "totals_sign_invalid",
                "Un avoir doit porter des montants négatifs ou nuls.",
            )
    elif any(total < 0 for total in totaux):
        erreur(
            "total_ttc",
            "totals_sign_invalid",
            "Une facture ne peut pas porter de montants négatifs (utilisez un avoir).",
        )

    if facture.total_ttc == 0:
        avertissement(
            "total_ttc",
            "total_amount_zero",
            "Le total TTC est à zéro : facture valide mais inhabituelle.",
        )

    # Limite documentée du MVP : aucune adresse émettrice en base.
    avertissement(
        "pays",
        "seller_country_defaulted",
        "Aucune adresse émettrice en base : pays FR appliqué par défaut "
        "dans le fichier.",
    )

    return RapportConformiteFacturX(
        conforme=not erreurs, erreurs=erreurs, avertissements=avertissements
    )
