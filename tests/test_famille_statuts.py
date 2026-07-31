"""Tests des prédicats de famille de statuts (source de vérité unique).

Les contrôles d'action raisonnent par famille (brouillon / émise) et jamais
par égalité stricte sur un libellé : les prédicats doivent être insensibles
à la casse et aux espaces (le seed écrit en minuscules, des données
existantes peuvent être capitalisées), et refuser dans le doute (statut
``None`` : aucune famille).
"""

import pytest
from src.factures.models import StatutFacture
from src.factures.statuts import est_annulee, est_brouillon, est_emise


def _statut(libelle: str) -> StatutFacture:
    return StatutFacture(id=1, libelle=libelle)


@pytest.mark.parametrize("libelle", ["brouillon", "Brouillon", " BROUILLON "])
def test_est_brouillon_insensible_a_la_casse(libelle: str) -> None:
    """La famille brouillon se reconnaît quelle que soit la casse stockée."""
    assert est_brouillon(_statut(libelle))
    assert not est_emise(_statut(libelle))


@pytest.mark.parametrize(
    "libelle",
    [
        "validée",
        "Validée",
        "payee",
        "partiellement_payee",
        "en_retard",
        "envoyee_client",
        "en_attente_pdp",
        "deposee_pdp",
        "rejetee_pdp",
        "erreur_transmission",
        "contestee",
        "annulee",
    ],
)
def test_est_emise_pour_toute_la_famille_non_brouillon(libelle: str) -> None:
    """Tout statut hors brouillon est une facture émise (scellée)."""
    assert est_emise(_statut(libelle))
    assert not est_brouillon(_statut(libelle))


def test_statut_inconnu_n_appartient_a_aucune_famille() -> None:
    """Sans statut chargé, on refuse tout : ni brouillon, ni émise."""
    assert not est_brouillon(None)
    assert not est_emise(None)
    assert not est_annulee(None)


@pytest.mark.parametrize(
    ("libelle", "attendu"),
    [("annulee", True), ("Annulee", True), ("payee", False), ("brouillon", False)],
)
def test_est_annulee(libelle: str, attendu: bool) -> None:
    """Seul le statut annulee (annulée par un avoir) est reconnu."""
    assert est_annulee(_statut(libelle)) is attendu
