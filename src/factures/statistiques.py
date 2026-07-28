"""
Agrégations SQL des statistiques de facturation.

Tout est calculé en base (``SUM`` / ``COUNT`` / ``GROUP BY``) : aucune facture
n'est chargée en mémoire, le coût est indépendant du volume. Python ne fait que
mettre en forme les lignes agrégées (arrondi, format des mois, comblement des
mois vides).

**Signe des avoirs.** Le signe stocké n'est pas fiable : un avoir généré depuis
une facture (``generer_avoir_brouillon``) est enregistré en négatif, alors qu'un
avoir saisi directement via ``POST /factures/`` est calculé depuis ses lignes et
ressort positif. Un ``SUM`` naïf donnerait donc un CA faux. Le signe est
normalisé en SQL (``-ABS(...)`` dès que ``type_facture = 'avoir'``) : un avoir
se soustrait toujours, quelle que soit la manière dont il a été créé.

**Factures annulées.** Elles restent comptées positivement : leur avoir les
neutralise déjà (facture +X, avoir −X, net 0). Les exclure tout en gardant
l'avoir donnerait un CA négatif.

Les constructeurs de requêtes sont des fonctions pures, sans session : ils sont
exécutables tels quels contre n'importe quel moteur, ce qui permet de vérifier
les chiffres dans les tests.
"""

from collections.abc import Sequence
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, TypedDict

from sqlalchemy import ColumnElement, Select, and_, case, extract, func, not_, select
from sqlalchemy.orm import Mapped
from sqlmodel import col
from sqlmodel.ext.asyncio.session import AsyncSession

from src.clients.models import Client
from src.factures.models import Facture, StatutFacture, TypeFacture
from src.factures.schemas import (
    DeviseExclue,
    IndicateursPaiement,
    PeriodeStatistiques,
    StatistiquesFactures,
    StatistiquesParClient,
    StatistiquesParMois,
    StatistiquesParStatut,
    TotauxBrouillons,
    TotauxStatistiques,
)

# Devise des montants agrégés par défaut : on n'additionne jamais deux devises.
DEVISE_PAR_DEFAUT = "EUR"

# Nombre de mois couverts quand aucune borne n'est fournie (12 mois glissants).
MOIS_PERIODE_PAR_DEFAUT = 12

LIMITE_TOP_CLIENTS_PAR_DEFAUT = 5
LIMITE_TOP_CLIENTS_MAX = 20

# Libellés du référentiel `statut_facture` (cf. src/core/seed.py). Comparés en
# `ilike` sans joker — égalité insensible à la casse, comme la route de liste.
LIBELLE_BROUILLON = "brouillon"

# Statuts qui soldent une facture : elle ne pèse plus sur l'encours client.
LIBELLES_SOLDES = ("payee", "annulee")

CENTIME = Decimal("0.01")


class Perimetre(TypedDict):
    """Filtres partagés par toutes les agrégations (isolation tenant comprise)."""

    id_entreprise: int
    date_min: date
    date_max: date
    devise: str


# ---------------------------------------------------------------------------
# Expressions SQL réutilisables
# ---------------------------------------------------------------------------


def _montant_signe(
    colonne: Mapped[Decimal] | ColumnElement[Decimal],
) -> ColumnElement[Decimal]:
    """Montant orienté comptablement : négatif pour un avoir, positif sinon.

    Normalise le signe au lieu de faire confiance au stockage (cf. docstring
    du module), pour qu'un avoir se soustraie toujours du chiffre d'affaires.
    """
    return case(
        (col(Facture.type_facture) == TypeFacture.AVOIR, -func.abs(colonne)),
        else_=colonne,
    )


def _statut_non_solde() -> ColumnElement[bool]:
    """Facture encore due : ni payée, ni annulée."""
    return and_(
        *(
            not_(col(StatutFacture.libelle).ilike(libelle))
            for libelle in LIBELLES_SOLDES
        )
    )


def _appliquer_perimetre(
    statement: Select[Any],
    *,
    id_entreprise: int,
    date_min: date,
    date_max: date,
    devise: str | None,
    brouillons: bool = False,
) -> Select[Any]:
    """Applique le périmètre commun à toutes les agrégations.

    Isolation tenant, bornes de dates incluses, devise unique, et famille de
    statuts : par défaut les documents émis (tout sauf brouillon, comme
    l'onglet « Validées » de la liste), ou les brouillons seuls si demandé.

    ``devise=None`` laisse toutes les devises : réservé au recensement des
    devises écartées, qui a besoin du même périmètre sans le filtre monétaire.
    """
    statement = statement.select_from(Facture).join(
        StatutFacture, onclause=col(Facture.id_statut) == col(StatutFacture.id)
    )
    statement = statement.where(
        col(Facture.id_entreprise) == id_entreprise,
        col(Facture.date_emission) >= date_min,
        col(Facture.date_emission) <= date_max,
    )
    if devise is not None:
        statement = statement.where(col(Facture.devise) == devise)
    filtre_brouillon = col(StatutFacture.libelle).ilike(LIBELLE_BROUILLON)
    return statement.where(filtre_brouillon if brouillons else not_(filtre_brouillon))


# ---------------------------------------------------------------------------
# Constructeurs de requêtes (fonctions pures)
# ---------------------------------------------------------------------------


def statement_totaux(
    *,
    id_entreprise: int,
    date_min: date,
    date_max: date,
    devise: str,
    aujourd_hui: date,
) -> Select[Any]:
    """Totaux de la période et encours client, en une seule requête.

    Colonnes : ca_ht, tva_collectee, ca_ttc, nombre_factures, nombre_avoirs,
    montant_en_retard, restant_a_encaisser.

    Le retard s'évalue sur ``date_echeance``, pas sur le statut ``en_retard``
    du référentiel : aucun traitement ne le pose aujourd'hui, l'indicateur
    serait donc systématiquement nul.
    """
    montant_ttc = _montant_signe(col(Facture.total_ttc))
    est_du = _statut_non_solde()
    est_en_retard = and_(
        col(Facture.date_echeance).is_not(None),
        col(Facture.date_echeance) < aujourd_hui,
        est_du,
    )

    statement = select(
        func.sum(_montant_signe(col(Facture.total_ht))),
        func.sum(_montant_signe(col(Facture.total_tva))),
        func.sum(montant_ttc),
        func.sum(case((col(Facture.type_facture) == TypeFacture.FACTURE, 1), else_=0)),
        func.sum(case((col(Facture.type_facture) == TypeFacture.AVOIR, 1), else_=0)),
        func.sum(case((est_en_retard, montant_ttc), else_=0)),
        func.sum(case((est_du, montant_ttc), else_=0)),
    )
    return _appliquer_perimetre(
        statement,
        id_entreprise=id_entreprise,
        date_min=date_min,
        date_max=date_max,
        devise=devise,
    )


def statement_par_statut(
    *, id_entreprise: int, date_min: date, date_max: date, devise: str
) -> Select[Any]:
    """Répartition par libellé de statut : (libellé, nombre, montant TTC).

    Le libellé sort du ``GROUP BY`` lui-même : aucune requête par ligne (N+1).
    """
    statement = select(
        col(StatutFacture.libelle),
        func.count(),
        func.sum(_montant_signe(col(Facture.total_ttc))),
    )
    statement = _appliquer_perimetre(
        statement,
        id_entreprise=id_entreprise,
        date_min=date_min,
        date_max=date_max,
        devise=devise,
    )
    return statement.group_by(col(StatutFacture.libelle)).order_by(
        col(StatutFacture.libelle)
    )


def statement_par_mois(
    *, id_entreprise: int, date_min: date, date_max: date, devise: str
) -> Select[Any]:
    """Série mensuelle : (année, mois, ca_ht, ca_ttc, nombre).

    ``extract`` plutôt que ``DATE_FORMAT`` : la même requête compile en MySQL
    (production) et en SQLite (tests). Le format ``YYYY-MM`` est assemblé côté
    Python depuis les deux entiers.
    """
    annee = extract("year", col(Facture.date_emission))
    mois = extract("month", col(Facture.date_emission))

    statement = select(
        annee,
        mois,
        func.sum(_montant_signe(col(Facture.total_ht))),
        func.sum(_montant_signe(col(Facture.total_ttc))),
        func.count(),
    )
    statement = _appliquer_perimetre(
        statement,
        id_entreprise=id_entreprise,
        date_min=date_min,
        date_max=date_max,
        devise=devise,
    )
    return statement.group_by(annee, mois).order_by(annee, mois)


def statement_top_clients(
    *,
    id_entreprise: int,
    date_min: date,
    date_max: date,
    devise: str,
    limite: int,
) -> Select[Any]:
    """Top clients par CA : (id_client, raison sociale, ca_ttc, nombre).

    Jointure externe sur ``client`` : les factures sans client rattaché
    forment un groupe à part plutôt que de disparaître. La raison sociale est
    ramenée par le ``GROUP BY`` (pas de N+1) et provient de la fiche client
    actuelle, volontairement — regrouper sur le snapshot figé dédoublerait un
    client renommé entre deux factures.
    """
    ca_ttc = func.sum(_montant_signe(col(Facture.total_ttc))).label("ca_ttc")

    statement = select(
        col(Facture.id_client), col(Client.raison_sociale), ca_ttc, func.count()
    )
    statement = _appliquer_perimetre(
        statement,
        id_entreprise=id_entreprise,
        date_min=date_min,
        date_max=date_max,
        devise=devise,
    )
    statement = statement.join(
        Client, onclause=col(Facture.id_client) == col(Client.id), isouter=True
    )
    return (
        statement.group_by(col(Facture.id_client), col(Client.raison_sociale))
        # id_client en départage : ordre stable entre deux clients à égalité.
        .order_by(ca_ttc.desc(), col(Facture.id_client))
        .limit(limite)
    )


def statement_devises_exclues(
    *, id_entreprise: int, date_min: date, date_max: date, devise: str
) -> Select[Any]:
    """Devises présentes sur la période mais écartées des totaux : (devise, nombre).

    Signale au front ce qui n'a pas été compté, plutôt que de le masquer.
    """
    statement = select(col(Facture.devise), func.count())
    # Même périmètre que les totaux, mais sans filtre de devise : on veut
    # exactement le complément de ce qui a été agrégé.
    statement = _appliquer_perimetre(
        statement,
        id_entreprise=id_entreprise,
        date_min=date_min,
        date_max=date_max,
        devise=None,
    ).where(col(Facture.devise) != devise)
    return statement.group_by(col(Facture.devise)).order_by(col(Facture.devise))


def statement_brouillons(
    *, id_entreprise: int, date_min: date, date_max: date, devise: str
) -> Select[Any]:
    """Brouillons de la période : (nombre, montant TTC).

    Hors chiffre d'affaires (un brouillon n'est pas émis), mais renvoyé pour
    éviter un second appel au front.
    """
    statement = select(func.count(), func.sum(_montant_signe(col(Facture.total_ttc))))
    return _appliquer_perimetre(
        statement,
        id_entreprise=id_entreprise,
        date_min=date_min,
        date_max=date_max,
        devise=devise,
        brouillons=True,
    )


# ---------------------------------------------------------------------------
# Mise en forme
# ---------------------------------------------------------------------------


def _montant(valeur: object) -> Decimal:
    """Normalise un agrégat monétaire en Decimal à deux décimales.

    Un ``SUM`` sur zéro ligne vaut NULL, et SQLite restitue les colonnes
    ``Numeric`` en flottant : l'arrondi explicite garantit une sortie
    identique quel que soit le moteur.
    """
    if valeur is None:
        return Decimal("0.00")
    return Decimal(str(valeur)).quantize(CENTIME, rounding=ROUND_HALF_UP)


def _premier_du_mois(jour: date) -> date:
    return date(jour.year, jour.month, 1)


def _decaler_mois(jour: date, decalage: int) -> date:
    """Décale de N mois en repartant du premier du mois (pas de débordement)."""
    index = jour.year * 12 + (jour.month - 1) + decalage
    return date(index // 12, index % 12 + 1, 1)


def resoudre_periode(
    date_min: date | None, date_max: date | None, aujourd_hui: date
) -> tuple[date, date]:
    """Complète les bornes manquantes par les 12 derniers mois glissants.

    Une période non bornée rendrait la série mensuelle illimitée ; le défaut
    correspond à la courbe d'évolution attendue par le tableau de bord. Pour
    du tout-temps, le client passe explicitement une ``date_min`` ancienne.
    """
    borne_max = date_max if date_max is not None else aujourd_hui
    if date_min is not None:
        return date_min, borne_max
    return _decaler_mois(borne_max, -(MOIS_PERIODE_PAR_DEFAUT - 1)), borne_max


def _mois_de_la_periode(date_min: date, date_max: date) -> list[str]:
    """Tous les mois couverts par la période, au format ``YYYY-MM``."""
    mois: list[str] = []
    curseur = _premier_du_mois(date_min)
    while curseur <= date_max:
        mois.append(f"{curseur.year:04d}-{curseur.month:02d}")
        curseur = _decaler_mois(curseur, 1)
    return mois


def _serie_mensuelle(
    lignes: Sequence[Any], date_min: date, date_max: date
) -> list[StatistiquesParMois]:
    """Complète la série mensuelle : les mois sans document sortent à zéro.

    Le front trace ainsi une courbe continue sans reboucher les trous. Il ne
    s'agit pas d'un calcul mais d'un remplissage : les agrégats viennent tous
    du ``GROUP BY`` SQL.
    """
    agregats = {
        f"{int(annee):04d}-{int(mois):02d}": StatistiquesParMois(
            mois=f"{int(annee):04d}-{int(mois):02d}",
            ca_ht=_montant(ca_ht),
            ca_ttc=_montant(ca_ttc),
            nombre=nombre,
        )
        for annee, mois, ca_ht, ca_ttc, nombre in lignes
    }
    return [
        agregats.get(
            mois,
            StatistiquesParMois(
                mois=mois, ca_ht=Decimal("0.00"), ca_ttc=Decimal("0.00"), nombre=0
            ),
        )
        for mois in _mois_de_la_periode(date_min, date_max)
    ]


def _totaux(ligne: Any) -> tuple[TotauxStatistiques, IndicateursPaiement]:
    """Éclate la ligne unique de ``statement_totaux`` en deux blocs de réponse."""
    ca_ht, tva, ca_ttc, nombre_factures, nombre_avoirs, retard, restant = ligne

    nombre_factures = int(nombre_factures or 0)
    ca_ttc_net = _montant(ca_ttc)
    panier_moyen = (
        (ca_ttc_net / nombre_factures).quantize(CENTIME, rounding=ROUND_HALF_UP)
        if nombre_factures
        else Decimal("0.00")
    )

    totaux = TotauxStatistiques(
        ca_ht=_montant(ca_ht),
        ca_ttc=ca_ttc_net,
        tva_collectee=_montant(tva),
        nombre_factures=nombre_factures,
        nombre_avoirs=int(nombre_avoirs or 0),
        panier_moyen=panier_moyen,
    )
    paiement = IndicateursPaiement(
        montant_en_retard=_montant(retard),
        restant_a_encaisser=_montant(restant),
    )
    return totaux, paiement


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


async def calculer_statistiques(
    session: AsyncSession,
    *,
    id_entreprise: int,
    date_min: date,
    date_max: date,
    devise: str,
    limite_top_clients: int,
    aujourd_hui: date,
) -> StatistiquesFactures:
    """Exécute les six agrégations et assemble la réponse.

    Six requêtes agrégées, aucune ligne de facture chargée : le coût ne dépend
    pas du nombre de factures de l'entreprise.
    """
    perimetre: Perimetre = {
        "id_entreprise": id_entreprise,
        "date_min": date_min,
        "date_max": date_max,
        "devise": devise,
    }

    resultat_totaux = await session.execute(
        statement_totaux(aujourd_hui=aujourd_hui, **perimetre)
    )
    totaux, paiement = _totaux(resultat_totaux.one())

    resultat_statut = await session.execute(statement_par_statut(**perimetre))
    par_statut = [
        StatistiquesParStatut(
            statut=libelle, nombre=nombre, montant_ttc=_montant(montant)
        )
        for libelle, nombre, montant in resultat_statut.all()
    ]

    resultat_mois = await session.execute(statement_par_mois(**perimetre))
    par_mois = _serie_mensuelle(resultat_mois.all(), date_min, date_max)

    resultat_clients = await session.execute(
        statement_top_clients(limite=limite_top_clients, **perimetre)
    )
    top_clients = [
        StatistiquesParClient(
            id_client=id_client,
            nom_client=nom_client,
            ca_ttc=_montant(ca_ttc),
            nombre=nombre,
        )
        for id_client, nom_client, ca_ttc, nombre in resultat_clients.all()
    ]

    resultat_devises = await session.execute(statement_devises_exclues(**perimetre))
    devises_exclues = [
        DeviseExclue(devise=code, nombre=nombre)
        for code, nombre in resultat_devises.all()
    ]

    resultat_brouillons = await session.execute(statement_brouillons(**perimetre))
    nombre_brouillons, montant_brouillons = resultat_brouillons.one()

    return StatistiquesFactures(
        periode=PeriodeStatistiques(date_min=date_min, date_max=date_max),
        devise=devise,
        totaux=totaux,
        par_statut=par_statut,
        par_mois=par_mois,
        top_clients=top_clients,
        paiement=paiement,
        devises_exclues=devises_exclues,
        brouillons=TotauxBrouillons(
            nombre=int(nombre_brouillons or 0),
            montant_ttc=_montant(montant_brouillons),
        ),
    )
