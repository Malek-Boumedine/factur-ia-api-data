"""Tests de la route d'agrégation des statistiques (``GET /factures/statistiques``).

Deux niveaux complémentaires :

- **les agrégations** sont exécutées contre la vraie base partagée de
  ``tests/conftest.py`` (SQLite en mémoire construite depuis
  ``SQLModel.metadata``, FK actives). Les constructeurs de requêtes étant des
  fonctions pures, les chiffres sont vérifiés pour de vrai — pas seulement la
  forme du SQL généré ;
- **la route** est testée avec la session factice des autres tests factures
  (isolation tenant, paramètres, période par défaut, forme de la réponse).
"""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlmodel import Session
from src.auth.dependencies import get_current_user, verify_tenant_access
from src.core.database import get_session
from src.entreprises.models import Entreprise
from src.factures.models import Facture, TypeFacture
from src.factures.router import router as factures_router
from src.factures.statistiques import (
    resoudre_periode,
    statement_brouillons,
    statement_devises_exclues,
    statement_par_mois,
    statement_par_statut,
    statement_top_clients,
    statement_totaux,
)
from src.utilisateurs.models import Utilisateur

from tests.factories import (
    STATUT_ANNULEE,
    STATUT_BROUILLON,
    STATUT_PAYEE,
    STATUT_VALIDEE,
    make_client,
    make_facture,
)

ENTREPRISE = 1
AUTRE_ENTREPRISE = 2

AUJOURD_HUI = date(2026, 7, 28)
PERIODE = {"date_min": date(2026, 1, 1), "date_max": date(2026, 12, 31)}


@pytest.fixture
def base(
    session: Session,
    entreprise: Entreprise,
    autre_entreprise: Entreprise,
    utilisateur: Utilisateur,
    statuts_facture: dict[str, int],
) -> Session:
    """Session sur une base portant le graphe référencé par les FK des factures."""
    return session


def _peupler(base: Session, factures: list[Facture]) -> None:
    """Insère le jeu de factures (le référentiel vient des fixtures)."""
    base.add_all(factures)
    base.commit()


# ---------------------------------------------------------------------------
# Agrégations : chiffres vérifiés contre une vraie base
# ---------------------------------------------------------------------------


def test_totaux_nets_des_avoirs(base: Session) -> None:
    """CA net, TVA et compteurs sur un jeu mixte factures / avoirs.

    Les deux avoirs couvrent les deux modes de stockage constatés en base :
    négatif pour un avoir généré depuis une facture, positif pour un avoir
    saisi directement. Les deux doivent se soustraire.
    """
    _peupler(
        base,
        [
            make_facture(
                numero="FAC-1",
                ht="1000.00",
                tva="200.00",
                ttc="1200.00",
                date_emission=date(2026, 3, 10),
            ),
            make_facture(
                numero="FAC-2",
                ht="500.00",
                tva="100.00",
                ttc="600.00",
                date_emission=date(2026, 4, 5),
            ),
            # Avoir généré : montants stockés en négatif.
            make_facture(
                numero="AV-1",
                ht="-200.00",
                tva="-40.00",
                ttc="-240.00",
                date_emission=date(2026, 4, 20),
                type_facture=TypeFacture.AVOIR,
            ),
            # Avoir saisi à la main : montants stockés en positif. Un SUM
            # naïf l'ajouterait au CA au lieu de le retrancher.
            make_facture(
                numero="AV-2",
                ht="100.00",
                tva="20.00",
                ttc="120.00",
                date_emission=date(2026, 5, 2),
                type_facture=TypeFacture.AVOIR,
            ),
        ],
    )
    ligne = base.execute(
        statement_totaux(
            id_entreprise=ENTREPRISE,
            devise="EUR",
            aujourd_hui=AUJOURD_HUI,
            **PERIODE,
        )
    ).one()

    ca_ht, tva, ca_ttc, nombre_factures, nombre_avoirs, _retard, _restant = ligne
    # 1000 + 500 - 200 - 100 = 1200
    assert Decimal(str(ca_ht)) == Decimal("1200.00")
    assert Decimal(str(tva)) == Decimal("240.00")
    assert Decimal(str(ca_ttc)) == Decimal("1440.00")
    assert nombre_factures == 2
    assert nombre_avoirs == 2


def test_brouillons_exclus_du_ca_et_comptes_a_part(base: Session) -> None:
    """Un brouillon ne pèse pas sur le CA mais ressort dans son propre bloc."""
    _peupler(
        base,
        [
            make_facture(
                numero="FAC-1",
                ht="1000.00",
                tva="200.00",
                ttc="1200.00",
                date_emission=date(2026, 3, 10),
            ),
            make_facture(
                numero="BROUILLON-X",
                ht="9999.00",
                tva="0.00",
                ttc="9999.00",
                date_emission=date(2026, 3, 11),
                id_statut=STATUT_BROUILLON,
            ),
        ],
    )
    totaux = base.execute(
        statement_totaux(
            id_entreprise=ENTREPRISE,
            devise="EUR",
            aujourd_hui=AUJOURD_HUI,
            **PERIODE,
        )
    ).one()
    brouillons = base.execute(
        statement_brouillons(id_entreprise=ENTREPRISE, devise="EUR", **PERIODE)
    ).one()

    assert Decimal(str(totaux[2])) == Decimal("1200.00")
    assert brouillons[0] == 1
    assert Decimal(str(brouillons[1])) == Decimal("9999.00")


def test_facture_annulee_neutralisee_par_son_avoir(base: Session) -> None:
    """Une facture annulée reste comptée positivement : avec son avoir, net 0.

    L'exclure tout en gardant l'avoir donnerait un CA négatif.
    """
    _peupler(
        base,
        [
            make_facture(
                numero="FAC-1",
                ht="800.00",
                tva="160.00",
                ttc="960.00",
                date_emission=date(2026, 2, 3),
                id_statut=STATUT_ANNULEE,
            ),
            make_facture(
                numero="AV-1",
                ht="-800.00",
                tva="-160.00",
                ttc="-960.00",
                date_emission=date(2026, 2, 4),
                id_statut=STATUT_VALIDEE,
                type_facture=TypeFacture.AVOIR,
            ),
        ],
    )
    ligne = base.execute(
        statement_totaux(
            id_entreprise=ENTREPRISE,
            devise="EUR",
            aujourd_hui=AUJOURD_HUI,
            **PERIODE,
        )
    ).one()

    assert Decimal(str(ligne[0])) == Decimal("0.00")
    assert Decimal(str(ligne[2])) == Decimal("0.00")


def test_isolation_tenant(base: Session) -> None:
    """Les factures d'une autre entreprise n'entrent dans aucune agrégation."""
    _peupler(
        base,
        [
            make_facture(
                numero="FAC-1",
                ht="100.00",
                tva="20.00",
                ttc="120.00",
                date_emission=date(2026, 3, 10),
            ),
            make_facture(
                id_entreprise=AUTRE_ENTREPRISE,
                numero="FAC-1",
                ht="5000.00",
                tva="1000.00",
                ttc="6000.00",
                date_emission=date(2026, 3, 10),
            ),
        ],
    )
    totaux = base.execute(
        statement_totaux(
            id_entreprise=ENTREPRISE,
            devise="EUR",
            aujourd_hui=AUJOURD_HUI,
            **PERIODE,
        )
    ).one()
    par_mois = base.execute(
        statement_par_mois(id_entreprise=ENTREPRISE, devise="EUR", **PERIODE)
    ).all()

    assert Decimal(str(totaux[2])) == Decimal("120.00")
    assert totaux[3] == 1
    assert len(par_mois) == 1
    assert Decimal(str(par_mois[0][3])) == Decimal("120.00")


def test_periode_filtree(base: Session) -> None:
    """Bornes de dates incluses : hors période, la facture n'est pas comptée."""
    _peupler(
        base,
        [
            make_facture(
                numero="AVANT",
                ht="100.00",
                tva="0.00",
                ttc="100.00",
                date_emission=date(2026, 5, 31),
            ),
            make_facture(
                numero="BORNE-MIN",
                ht="200.00",
                tva="0.00",
                ttc="200.00",
                date_emission=date(2026, 6, 1),
            ),
            make_facture(
                numero="BORNE-MAX",
                ht="300.00",
                tva="0.00",
                ttc="300.00",
                date_emission=date(2026, 6, 30),
            ),
            make_facture(
                numero="APRES",
                ht="400.00",
                tva="0.00",
                ttc="400.00",
                date_emission=date(2026, 7, 1),
            ),
        ],
    )
    ligne = base.execute(
        statement_totaux(
            id_entreprise=ENTREPRISE,
            date_min=date(2026, 6, 1),
            date_max=date(2026, 6, 30),
            devise="EUR",
            aujourd_hui=AUJOURD_HUI,
        )
    ).one()

    # Les deux bornes sont incluses, rien autour.
    assert Decimal(str(ligne[2])) == Decimal("500.00")
    assert ligne[3] == 2


def test_devises_non_eur_exclues_et_signalees(base: Session) -> None:
    """Les autres devises sortent des totaux et sont remontées séparément."""
    _peupler(
        base,
        [
            make_facture(
                numero="FAC-EUR",
                ht="100.00",
                tva="0.00",
                ttc="100.00",
                date_emission=date(2026, 3, 10),
            ),
            make_facture(
                numero="FAC-USD",
                ht="900.00",
                tva="0.00",
                ttc="900.00",
                date_emission=date(2026, 3, 11),
                devise="USD",
            ),
            make_facture(
                numero="FAC-USD-2",
                ht="800.00",
                tva="0.00",
                ttc="800.00",
                date_emission=date(2026, 3, 12),
                devise="USD",
            ),
            make_facture(
                numero="FAC-CHF",
                ht="700.00",
                tva="0.00",
                ttc="700.00",
                date_emission=date(2026, 3, 13),
                devise="CHF",
            ),
        ],
    )
    totaux = base.execute(
        statement_totaux(
            id_entreprise=ENTREPRISE,
            devise="EUR",
            aujourd_hui=AUJOURD_HUI,
            **PERIODE,
        )
    ).one()
    exclues = base.execute(
        statement_devises_exclues(id_entreprise=ENTREPRISE, devise="EUR", **PERIODE)
    ).all()

    assert Decimal(str(totaux[2])) == Decimal("100.00")
    assert [(devise, nombre) for devise, nombre in exclues] == [("CHF", 1), ("USD", 2)]


def test_repartition_par_statut(base: Session) -> None:
    """Nombre et montant par libellé de statut, résolus par la jointure."""
    _peupler(
        base,
        [
            make_facture(
                numero="FAC-1",
                ht="100.00",
                tva="0.00",
                ttc="100.00",
                date_emission=date(2026, 3, 10),
            ),
            make_facture(
                numero="FAC-2",
                ht="200.00",
                tva="0.00",
                ttc="200.00",
                date_emission=date(2026, 3, 11),
            ),
            make_facture(
                numero="FAC-3",
                ht="300.00",
                tva="0.00",
                ttc="300.00",
                date_emission=date(2026, 3, 12),
                id_statut=STATUT_PAYEE,
            ),
        ],
    )
    lignes = base.execute(
        statement_par_statut(id_entreprise=ENTREPRISE, devise="EUR", **PERIODE)
    ).all()

    assert [
        (libelle, nombre, Decimal(str(montant))) for libelle, nombre, montant in lignes
    ] == [
        ("payee", 1, Decimal("300.00")),
        ("validée", 2, Decimal("300.00")),
    ]


def test_serie_mensuelle(base: Session) -> None:
    """Regroupement par mois d'émission, ordonné, avoirs soustraits."""
    _peupler(
        base,
        [
            make_facture(
                numero="FAC-1",
                ht="100.00",
                tva="20.00",
                ttc="120.00",
                date_emission=date(2026, 1, 15),
            ),
            make_facture(
                numero="FAC-2",
                ht="200.00",
                tva="40.00",
                ttc="240.00",
                date_emission=date(2026, 3, 2),
            ),
            make_facture(
                numero="AV-1",
                ht="50.00",
                tva="10.00",
                ttc="60.00",
                date_emission=date(2026, 3, 20),
                type_facture=TypeFacture.AVOIR,
            ),
        ],
    )
    lignes = base.execute(
        statement_par_mois(id_entreprise=ENTREPRISE, devise="EUR", **PERIODE)
    ).all()

    resultat = [
        (int(annee), int(mois), Decimal(str(ca_ht)), Decimal(str(ca_ttc)), nombre)
        for annee, mois, ca_ht, ca_ttc, nombre in lignes
    ]
    assert resultat == [
        (2026, 1, Decimal("100.00"), Decimal("120.00"), 1),
        # 200 - 50 = 150 HT, l'avoir positif est bien soustrait
        (2026, 3, Decimal("150.00"), Decimal("180.00"), 2),
    ]


def test_top_clients(base: Session) -> None:
    """Classement par CA décroissant, nom résolu par la jointure, limite appliquée.

    Les factures sans client rattaché forment un groupe à ``id_client`` null
    au lieu de disparaître (jointure externe).
    """
    base.add_all(
        [
            make_client(id=10, raison_sociale="Petit Client"),
            make_client(id=11, raison_sociale="Gros Client"),
        ]
    )
    _peupler(
        base,
        [
            make_facture(
                numero="FAC-1",
                ht="100.00",
                tva="0.00",
                ttc="100.00",
                date_emission=date(2026, 3, 10),
                id_client=10,
            ),
            make_facture(
                numero="FAC-2",
                ht="900.00",
                tva="0.00",
                ttc="900.00",
                date_emission=date(2026, 3, 11),
                id_client=11,
            ),
            make_facture(
                numero="FAC-3",
                ht="500.00",
                tva="0.00",
                ttc="500.00",
                date_emission=date(2026, 3, 12),
                id_client=11,
            ),
            make_facture(
                numero="FAC-4",
                ht="300.00",
                tva="0.00",
                ttc="300.00",
                date_emission=date(2026, 3, 13),
            ),
        ],
    )
    lignes = base.execute(
        statement_top_clients(
            id_entreprise=ENTREPRISE, devise="EUR", limite=10, **PERIODE
        )
    ).all()

    assert [
        (id_client, nom, Decimal(str(ca)), nombre)
        for id_client, nom, ca, nombre in lignes
    ] == [
        (11, "Gros Client", Decimal("1400.00"), 2),
        (None, None, Decimal("300.00"), 1),
        (10, "Petit Client", Decimal("100.00"), 1),
    ]

    limitees = base.execute(
        statement_top_clients(
            id_entreprise=ENTREPRISE, devise="EUR", limite=1, **PERIODE
        )
    ).all()
    assert len(limitees) == 1
    assert limitees[0][0] == 11


def test_encours_et_montant_en_retard(base: Session) -> None:
    """Retard fondé sur la date d'échéance, encours excluant payées et annulées.

    Le statut ``en_retard`` du référentiel n'est jamais posé par l'API : un
    indicateur qui s'y fierait serait toujours nul.
    """
    _peupler(
        base,
        [
            # Échue et non soldée : en retard, et dans l'encours.
            make_facture(
                numero="FAC-RETARD",
                ht="1000.00",
                tva="0.00",
                ttc="1000.00",
                date_emission=date(2026, 3, 1),
                date_echeance=date(2026, 4, 1),
            ),
            # Échéance à venir : dans l'encours seulement.
            make_facture(
                numero="FAC-A-VENIR",
                ht="500.00",
                tva="0.00",
                ttc="500.00",
                date_emission=date(2026, 7, 1),
                date_echeance=date(2026, 9, 1),
            ),
            # Échue mais payée : ni retard, ni encours.
            make_facture(
                numero="FAC-PAYEE",
                ht="700.00",
                tva="0.00",
                ttc="700.00",
                date_emission=date(2026, 2, 1),
                date_echeance=date(2026, 3, 1),
                id_statut=STATUT_PAYEE,
            ),
            # Échue mais annulée : ni retard, ni encours.
            make_facture(
                numero="FAC-ANNULEE",
                ht="300.00",
                tva="0.00",
                ttc="300.00",
                date_emission=date(2026, 2, 2),
                date_echeance=date(2026, 3, 2),
                id_statut=STATUT_ANNULEE,
            ),
            # Sans échéance : jamais en retard, mais toujours dû.
            make_facture(
                numero="FAC-SANS-ECHEANCE",
                ht="200.00",
                tva="0.00",
                ttc="200.00",
                date_emission=date(2026, 3, 5),
            ),
        ],
    )
    ligne = base.execute(
        statement_totaux(
            id_entreprise=ENTREPRISE,
            devise="EUR",
            aujourd_hui=AUJOURD_HUI,
            **PERIODE,
        )
    ).one()

    _ca_ht, _tva, _ca_ttc, _nb, _nb_avoirs, retard, restant = ligne
    assert Decimal(str(retard)) == Decimal("1000.00")
    # Retard + à venir + sans échéance ; payée et annulée exclues.
    assert Decimal(str(restant)) == Decimal("1700.00")


def test_aucune_facture_agregats_nuls(base: Session) -> None:
    """Période vide : les SUM valent NULL en SQL, jamais une erreur."""
    ligne = base.execute(
        statement_totaux(
            id_entreprise=ENTREPRISE,
            devise="EUR",
            aujourd_hui=AUJOURD_HUI,
            **PERIODE,
        )
    ).one()

    assert ligne[0] is None
    assert ligne[2] is None


# ---------------------------------------------------------------------------
# Période par défaut (fonction pure)
# ---------------------------------------------------------------------------


def test_periode_par_defaut_douze_mois_glissants() -> None:
    """Sans bornes : du 1er du mois 11 mois en arrière jusqu'à aujourd'hui."""
    date_min, date_max = resoudre_periode(None, None, date(2026, 7, 28))
    assert date_min == date(2025, 8, 1)
    assert date_max == date(2026, 7, 28)

    # Passage d'année en début de mois
    date_min, _ = resoudre_periode(None, None, date(2026, 1, 15))
    assert date_min == date(2025, 2, 1)


def test_periode_partiellement_fournie() -> None:
    """Une seule borne fournie : l'autre est complétée, celle donnée est gardée."""
    date_min, date_max = resoudre_periode(date(2020, 1, 1), None, AUJOURD_HUI)
    assert (date_min, date_max) == (date(2020, 1, 1), AUJOURD_HUI)

    date_min, date_max = resoudre_periode(None, date(2026, 3, 31), AUJOURD_HUI)
    assert (date_min, date_max) == (date(2025, 4, 1), date(2026, 3, 31))


# ---------------------------------------------------------------------------
# Route : isolation tenant, paramètres, forme de la réponse
# ---------------------------------------------------------------------------


class _Result:
    def __init__(self, value: Any) -> None:
        self._value = value

    def one(self) -> Any:
        return self._value

    def all(self) -> Any:
        return self._value


class _FakeSession:
    """Session factice : dépile des résultats prévus et trace les requêtes."""

    def __init__(self, results: list[Any]) -> None:
        self._results = results
        self.statements: list[Any] = []

    async def execute(self, statement: Any) -> _Result:
        self.statements.append(statement)
        return _Result(self._results.pop(0))


def _resultats_types() -> list[Any]:
    """Retours des six agrégations, dans l'ordre où la route les exécute."""
    return [
        # totaux : ca_ht, tva, ca_ttc, nb factures, nb avoirs, retard, restant
        (
            Decimal("1000.00"),
            Decimal("200.00"),
            Decimal("1200.00"),
            3,
            1,
            Decimal("400.00"),
            Decimal("900.00"),
        ),
        [("validée", 2, Decimal("800.00")), ("payee", 1, Decimal("400.00"))],
        [(2026, 7, Decimal("1000.00"), Decimal("1200.00"), 4)],
        [(11, "Gros Client", Decimal("1200.00"), 4)],
        [("USD", 2)],
        (5, Decimal("6100.00")),
    ]


def _app(session: _FakeSession, *, authenticated: bool = True) -> FastAPI:
    app = FastAPI()
    app.include_router(factures_router)
    app.dependency_overrides[get_session] = lambda: session
    if authenticated:
        app.dependency_overrides[get_current_user] = lambda: Utilisateur(
            id=1,
            nom="Test",
            prenom="User",
            email="user@example.com",
            hash_mot_de_passe="x",  # pragma: allowlist secret
        )
        app.dependency_overrides[verify_tenant_access] = lambda: ENTREPRISE
    return app


async def _get(app: FastAPI, params: dict[str, Any] | None = None) -> Any:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get("/factures/statistiques", params=params or {})


def _bound_params(statement: Any) -> list[Any]:
    return list(statement.compile().params.values())


async def test_route_reponse_complete() -> None:
    """La réponse assemble les six agrégations, avec le panier moyen calculé."""
    session = _FakeSession(_resultats_types())
    response = await _get(
        _app(session), {"date_min": "2026-07-01", "date_max": "2026-07-31"}
    )

    assert response.status_code == 200
    body = response.json()

    assert body["periode"] == {"date_min": "2026-07-01", "date_max": "2026-07-31"}
    assert body["devise"] == "EUR"
    assert body["totaux"] == {
        "ca_ht": "1000.00",
        "ca_ttc": "1200.00",
        "tva_collectee": "200.00",
        "nombre_factures": 3,
        "nombre_avoirs": 1,
        # 1200 / 3 : les avoirs pèsent au numérateur, pas au dénominateur
        "panier_moyen": "400.00",
    }
    assert body["par_statut"][0] == {
        "statut": "validée",
        "nombre": 2,
        "montant_ttc": "800.00",
    }
    assert body["top_clients"] == [
        {
            "id_client": 11,
            "nom_client": "Gros Client",
            "ca_ttc": "1200.00",
            "nombre": 4,
        }
    ]
    assert body["paiement"] == {
        "montant_en_retard": "400.00",
        "restant_a_encaisser": "900.00",
    }
    assert body["devises_exclues"] == [{"devise": "USD", "nombre": 2}]
    assert body["brouillons"] == {"nombre": 5, "montant_ttc": "6100.00"}

    # Isolation tenant sur chacune des six agrégations
    assert len(session.statements) == 6
    for statement in session.statements:
        assert "id_entreprise" in str(statement)
        assert ENTREPRISE in _bound_params(statement)


async def test_route_serie_mensuelle_completee() -> None:
    """Les mois sans facture sont renvoyés à zéro : courbe continue côté front."""
    session = _FakeSession(_resultats_types())
    response = await _get(
        _app(session), {"date_min": "2026-05-15", "date_max": "2026-07-31"}
    )

    assert response.status_code == 200
    par_mois = response.json()["par_mois"]
    assert [point["mois"] for point in par_mois] == ["2026-05", "2026-06", "2026-07"]
    assert par_mois[0] == {
        "mois": "2026-05",
        "ca_ht": "0.00",
        "ca_ttc": "0.00",
        "nombre": 0,
    }
    assert par_mois[2]["ca_ttc"] == "1200.00"


async def test_route_periode_par_defaut_dans_la_reponse() -> None:
    """Sans bornes, la période appliquée est renvoyée (le front la réutilise)."""
    session = _FakeSession(_resultats_types())
    response = await _get(_app(session))

    assert response.status_code == 200
    periode = response.json()["periode"]
    attendu_min, attendu_max = resoudre_periode(None, None, date.today())
    assert periode == {
        "date_min": attendu_min.isoformat(),
        "date_max": attendu_max.isoformat(),
    }
    # La période par défaut couvre bien 12 points mensuels
    assert len(response.json()["par_mois"]) == 12


async def test_route_devise_et_limite_appliquees() -> None:
    """Les paramètres devise et limite_top_clients arrivent jusqu'au SQL."""
    session = _FakeSession(_resultats_types())
    response = await _get(_app(session), {"devise": "usd", "limite_top_clients": 3})

    assert response.status_code == 200
    # Devise normalisée en majuscules et propagée à toutes les requêtes
    assert response.json()["devise"] == "USD"
    for statement in session.statements:
        assert "USD" in _bound_params(statement)
    # La limite borne la requête top clients (4e agrégation exécutée)
    assert 3 in _bound_params(session.statements[3])


async def test_route_periode_incoherente_400() -> None:
    """date_min postérieure à date_max : refusée avant toute requête."""
    session = _FakeSession([])
    response = await _get(
        _app(session), {"date_min": "2026-07-31", "date_max": "2026-07-01"}
    )

    assert response.status_code == 400
    assert session.statements == []


async def test_route_limite_hors_bornes_422() -> None:
    """limite_top_clients au-delà du plafond : rejetée avant toute requête."""
    session = _FakeSession([])
    response = await _get(_app(session), {"limite_top_clients": 999})

    assert response.status_code == 422
    assert session.statements == []


async def test_route_non_authentifiee_401() -> None:
    """Sans token, la route est inaccessible (401)."""
    session = _FakeSession([])
    app = _app(session, authenticated=False)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/factures/statistiques", headers={"X-Entreprise-Id": "1"}
        )

    assert response.status_code == 401
    assert session.statements == []


async def test_statistiques_non_capturee_par_le_parametre_de_chemin() -> None:
    """`/factures/statistiques` ne doit pas être résolu comme `/factures/{id}`.

    La route est déclarée avant celle de détail ; l'ordre inverse produirait un
    422 sur la conversion de « statistiques » en entier.
    """
    session = _FakeSession(_resultats_types())
    response = await _get(_app(session))

    assert response.status_code == 200
    assert "periode" in response.json()
