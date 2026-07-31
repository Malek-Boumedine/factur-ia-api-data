"""Familles de statuts de facture : source de vérité unique.

Le cycle de vie d'une facture (référentiel ``statut_facture``, cf.
``src/core/seed.py``) se partage en deux familles : la famille « brouillon »
(état de travail, modifiable et supprimable) et la famille « émise » (facture
scellée à la validation — validée, payée, en retard, statuts PDP…). Les
contrôles d'action doivent raisonner par famille, jamais par égalité stricte
sur un libellé : une facture qui progresse dans son cycle de vie reste une
facture émise, et les actions qui lui sont permises doivent le rester.

Les comparaisons sont insensibles à la casse et aux espaces : le seed écrit
les libellés en minuscules, mais des données existantes peuvent être
capitalisées (MySQL compare sans tenir compte de la casse côté SQL, Python
non). Un statut absent (``None``) n'appartient à aucune famille : dans le
doute, chaque prédicat répond ``False`` et l'action est refusée.
"""

from src.factures.models import StatutFacture

LIBELLE_BROUILLON = "brouillon"
LIBELLE_ANNULEE = "annulee"


def _libelle_normalise(statut: StatutFacture) -> str:
    return statut.libelle.strip().lower()


def est_brouillon(statut: StatutFacture | None) -> bool:
    """État de travail : facture non émise, encore modifiable."""
    return statut is not None and _libelle_normalise(statut) == LIBELLE_BROUILLON


def est_emise(statut: StatutFacture | None) -> bool:
    """Facture scellée par la validation, quel que soit son avancement."""
    return statut is not None and _libelle_normalise(statut) != LIBELLE_BROUILLON


def est_annulee(statut: StatutFacture | None) -> bool:
    """Facture annulée par un avoir."""
    return statut is not None and _libelle_normalise(statut) == LIBELLE_ANNULEE
