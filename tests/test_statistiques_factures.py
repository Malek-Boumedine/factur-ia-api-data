"""Tests de la route d'agrégation des statistiques (``GET /factures/statistiques``).

Deux niveaux complémentaires :

- **les agrégations** sont exécutées contre une vraie base SQLite en mémoire
  construite depuis ``SQLModel.metadata`` (même approche que
  ``test_unicite_numero_facture.py``). Les constructeurs de requêtes étant des
  fonctions pures, les chiffres sont vérifiés pour de vrai — pas seulement la
  forme du SQL généré ;
- **la route** est testée avec la session factice des autres tests factures
  (isolation tenant, paramètres, période par défaut, forme de la réponse).
"""

from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from typing import Any

# L'import de tous les modules de modèles (comme dans migrations/env.py) est
# nécessaire pour que SQLModel.metadata contienne les tables référencées par
# les clés étrangères de Facture.
import pytest
import src.abonnements.models  # noqa: F401
import src.audit.models  # noqa: F401
import src.auth.models  # noqa: F401
import src.catalogue_produits.models  # noqa: F401
import src.documents.models  # noqa: F401
import src.entreprises.models  # noqa: F401
import src.notifications.models  # noqa: F401
import src.pdp.models  # noqa: F401
import src.relances.models  # noqa: F401
import src.utilisateurs.models  # noqa: F401
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine
from src.auth.dependencies import get_current_user, verify_tenant_access
from src.clients.models import Client
from src.core.database import get_session
from src.factures.models import Facture, StatutFacture, TypeFacture
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

# Statuts du référentiel utilisés par les scénarios (cf. src/core/seed.py).
STATUT_BROUILLON = 1
STATUT_VALIDEE = 2
STATUT_PAYEE = 3
STATUT_ANNULEE = 4

ENTREPRISE = 1
AUTRE_ENTREPRISE = 2

AUJOURD_HUI = date(2026, 7, 28)
PERIODE = {"date_min": date(2026, 1, 1), "date_max": date(2026, 12, 31)}


@pytest.fixture
def engine() -> Iterator[Engine]:
    """Base SQLite en mémoire avec le schéma complet des modèles."""
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    yield engine
    engine.dispose()


def _facture(
    *,
    id_entreprise: int = ENTREPRISE,
    numero: str,
    ht: str,
    tva: str,
    ttc: str,
    date_emission: date,
    id_statut: int = STATUT_VALIDEE,
    type_facture: TypeFacture = TypeFacture.FACTURE,
    id_client: int | None = None,
    devise: str = "EUR",
    date_echeance: date | None = None,
) -> Facture:
    # SQLite n'applique pas les FK par défaut : les identifiants liés sont
    # arbitraires quand le test ne porte pas sur la jointure.
    return Facture(
        id_entreprise=id_entreprise,
        id_createur=1,
        id_client=id_client,
        numero_facture=numero,
        date_emission=date_emission,
        date_echeance=date_echeance,
        devise=devise,
        type_facture=type_facture,
        id_statut=id_statut,
        total_ht=Decimal(ht),
        total_tva=Decimal(tva),
        total_ttc=Decimal(ttc),
    )


def _client(id_client: int, raison_sociale: str) -> Client:
    return Client(
        id=id_client,
        id_entreprise=ENTREPRISE,
        id_createur=1,
        raison_sociale=raison_sociale,
        code_postal="75001",
        ville="Paris",
    )


def _peupler(session: Session, factures: list[Facture]) -> None:
    """Insère le référentiel des statuts puis le jeu de factures."""
    session.add_all(
        [
            StatutFacture(id=STATUT_BROUILLON, libelle="brouillon"),
            StatutFacture(id=STATUT_VALIDEE, libelle="validée"),
            StatutFacture(id=STATUT_PAYEE, libelle="payee"),
            StatutFacture(id=STATUT_ANNULEE, libelle="annulee"),
        ]
    )
    session.add_all(factures)
    session.commit()


# ---------------------------------------------------------------------------
# Agrégations : chiffres vérifiés contre une vraie base
# ---------------------------------------------------------------------------


def test_totaux_nets_des_avoirs(engine: Engine) -> None:
    """CA net, TVA et compteurs sur un jeu mixte factures / avoirs.

    Les deux avoirs couvrent les deux modes de stockage constatés en base :
    négatif pour un avoir généré depuis une facture, positif pour un avoir
    saisi directement. Les deux doivent se soustraire.
    """
    with Session(engine) as session:
        _peupler(
            session,
            [
                _facture(
                    numero="FAC-1",
                    ht="1000.00",
                    tva="200.00",
                    ttc="1200.00",
                    date_emission=date(2026, 3, 10),
                ),
                _facture(
                    numero="FAC-2",
                    ht="500.00",
                    tva="100.00",
                    ttc="600.00",
                    date_emission=date(2026, 4, 5),
                ),
                # Avoir généré : montants stockés en négatif.
                _facture(
                    numero="AV-1",
                    ht="-200.00",
                    tva="-40.00",
                    ttc="-240.00",
                    date_emission=date(2026, 4, 20),
                    type_facture=TypeFacture.AVOIR,
                ),
                # Avoir saisi à la main : montants stockés en positif. Un SUM
                # naïf l'ajouterait au CA au lieu de le retrancher.
                _facture(
                    numero="AV-2",
                    ht="100.00",
                    tva="20.00",
                    ttc="120.00",
                    date_emission=date(2026, 5, 2),
                    type_facture=TypeFacture.AVOIR,
                ),
            ],
        )
        ligne = session.execute(
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


def test_brouillons_exclus_du_ca_et_comptes_a_part(engine: Engine) -> None:
    """Un brouillon ne pèse pas sur le CA mais ressort dans son propre bloc."""
    with Session(engine) as session:
        _peupler(
            session,
            [
                _facture(
                    numero="FAC-1",
                    ht="1000.00",
                    tva="200.00",
                    ttc="1200.00",
                    date_emission=date(2026, 3, 10),
                ),
                _facture(
                    numero="BROUILLON-X",
                    ht="9999.00",
                    tva="0.00",
                    ttc="9999.00",
                    date_emission=date(2026, 3, 11),
                    id_statut=STATUT_BROUILLON,
                ),
            ],
        )
        totaux = session.execute(
            statement_totaux(
                id_entreprise=ENTREPRISE,
                devise="EUR",
                aujourd_hui=AUJOURD_HUI,
                **PERIODE,
            )
        ).one()
        brouillons = session.execute(
            statement_brouillons(id_entreprise=ENTREPRISE, devise="EUR", **PERIODE)
        ).one()

    assert Decimal(str(totaux[2])) == Decimal("1200.00")
    assert brouillons[0] == 1
    assert Decimal(str(brouillons[1])) == Decimal("9999.00")


def test_facture_annulee_neutralisee_par_son_avoir(engine: Engine) -> None:
    """Une facture annulée reste comptée positivement : avec son avoir, net 0.

    L'exclure tout en gardant l'avoir donnerait un CA négatif.
    """
    with Session(engine) as session:
        _peupler(
            session,
            [
                _facture(
                    numero="FAC-1",
                    ht="800.00",
                    tva="160.00",
                    ttc="960.00",
                    date_emission=date(2026, 2, 3),
                    id_statut=STATUT_ANNULEE,
                ),
                _facture(
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
        ligne = session.execute(
            statement_totaux(
                id_entreprise=ENTREPRISE,
                devise="EUR",
                aujourd_hui=AUJOURD_HUI,
                **PERIODE,
            )
        ).one()

    assert Decimal(str(ligne[0])) == Decimal("0.00")
    assert Decimal(str(ligne[2])) == Decimal("0.00")


def test_isolation_tenant(engine: Engine) -> None:
    """Les factures d'une autre entreprise n'entrent dans aucune agrégation."""
    with Session(engine) as session:
        _peupler(
            session,
            [
                _facture(
                    numero="FAC-1",
                    ht="100.00",
                    tva="20.00",
                    ttc="120.00",
                    date_emission=date(2026, 3, 10),
                ),
                _facture(
                    id_entreprise=AUTRE_ENTREPRISE,
                    numero="FAC-1",
                    ht="5000.00",
                    tva="1000.00",
                    ttc="6000.00",
                    date_emission=date(2026, 3, 10),
                ),
            ],
        )
        totaux = session.execute(
            statement_totaux(
                id_entreprise=ENTREPRISE,
                devise="EUR",
                aujourd_hui=AUJOURD_HUI,
                **PERIODE,
            )
        ).one()
        par_mois = session.execute(
            statement_par_mois(id_entreprise=ENTREPRISE, devise="EUR", **PERIODE)
        ).all()

    assert Decimal(str(totaux[2])) == Decimal("120.00")
    assert totaux[3] == 1
    assert len(par_mois) == 1
    assert Decimal(str(par_mois[0][3])) == Decimal("120.00")


def test_periode_filtree(engine: Engine) -> None:
    """Bornes de dates incluses : hors période, la facture n'est pas comptée."""
    with Session(engine) as session:
        _peupler(
            session,
            [
                _facture(
                    numero="AVANT",
                    ht="100.00",
                    tva="0.00",
                    ttc="100.00",
                    date_emission=date(2026, 5, 31),
                ),
                _facture(
                    numero="BORNE-MIN",
                    ht="200.00",
                    tva="0.00",
                    ttc="200.00",
                    date_emission=date(2026, 6, 1),
                ),
                _facture(
                    numero="BORNE-MAX",
                    ht="300.00",
                    tva="0.00",
                    ttc="300.00",
                    date_emission=date(2026, 6, 30),
                ),
                _facture(
                    numero="APRES",
                    ht="400.00",
                    tva="0.00",
                    ttc="400.00",
                    date_emission=date(2026, 7, 1),
                ),
            ],
        )
        ligne = session.execute(
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


def test_devises_non_eur_exclues_et_signalees(engine: Engine) -> None:
    """Les autres devises sortent des totaux et sont remontées séparément."""
    with Session(engine) as session:
        _peupler(
            session,
            [
                _facture(
                    numero="FAC-EUR",
                    ht="100.00",
                    tva="0.00",
                    ttc="100.00",
                    date_emission=date(2026, 3, 10),
                ),
                _facture(
                    numero="FAC-USD",
                    ht="900.00",
                    tva="0.00",
                    ttc="900.00",
                    date_emission=date(2026, 3, 11),
                    devise="USD",
                ),
                _facture(
                    numero="FAC-USD-2",
                    ht="800.00",
                    tva="0.00",
                    ttc="800.00",
                    date_emission=date(2026, 3, 12),
                    devise="USD",
                ),
                _facture(
                    numero="FAC-CHF",
                    ht="700.00",
                    tva="0.00",
                    ttc="700.00",
                    date_emission=date(2026, 3, 13),
                    devise="CHF",
                ),
            ],
        )
        totaux = session.execute(
            statement_totaux(
                id_entreprise=ENTREPRISE,
                devise="EUR",
                aujourd_hui=AUJOURD_HUI,
                **PERIODE,
            )
        ).one()
        exclues = session.execute(
            statement_devises_exclues(id_entreprise=ENTREPRISE, devise="EUR", **PERIODE)
        ).all()

    assert Decimal(str(totaux[2])) == Decimal("100.00")
    assert [(devise, nombre) for devise, nombre in exclues] == [("CHF", 1), ("USD", 2)]


def test_repartition_par_statut(engine: Engine) -> None:
    """Nombre et montant par libellé de statut, résolus par la jointure."""
    with Session(engine) as session:
        _peupler(
            session,
            [
                _facture(
                    numero="FAC-1",
                    ht="100.00",
                    tva="0.00",
                    ttc="100.00",
                    date_emission=date(2026, 3, 10),
                ),
                _facture(
                    numero="FAC-2",
                    ht="200.00",
                    tva="0.00",
                    ttc="200.00",
                    date_emission=date(2026, 3, 11),
                ),
                _facture(
                    numero="FAC-3",
                    ht="300.00",
                    tva="0.00",
                    ttc="300.00",
                    date_emission=date(2026, 3, 12),
                    id_statut=STATUT_PAYEE,
                ),
            ],
        )
        lignes = session.execute(
            statement_par_statut(id_entreprise=ENTREPRISE, devise="EUR", **PERIODE)
        ).all()

    assert [
        (libelle, nombre, Decimal(str(montant))) for libelle, nombre, montant in lignes
    ] == [
        ("payee", 1, Decimal("300.00")),
        ("validée", 2, Decimal("300.00")),
    ]


def test_serie_mensuelle(engine: Engine) -> None:
    """Regroupement par mois d'émission, ordonné, avoirs soustraits."""
    with Session(engine) as session:
        _peupler(
            session,
            [
                _facture(
                    numero="FAC-1",
                    ht="100.00",
                    tva="20.00",
                    ttc="120.00",
                    date_emission=date(2026, 1, 15),
                ),
                _facture(
                    numero="FAC-2",
                    ht="200.00",
                    tva="40.00",
                    ttc="240.00",
                    date_emission=date(2026, 3, 2),
                ),
                _facture(
                    numero="AV-1",
                    ht="50.00",
                    tva="10.00",
                    ttc="60.00",
                    date_emission=date(2026, 3, 20),
                    type_facture=TypeFacture.AVOIR,
                ),
            ],
        )
        lignes = session.execute(
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


def test_top_clients(engine: Engine) -> None:
    """Classement par CA décroissant, nom résolu par la jointure, limite appliquée.

    Les factures sans client rattaché forment un groupe à ``id_client`` null
    au lieu de disparaître (jointure externe).
    """
    with Session(engine) as session:
        session.add_all([_client(10, "Petit Client"), _client(11, "Gros Client")])
        _peupler(
            session,
            [
                _facture(
                    numero="FAC-1",
                    ht="100.00",
                    tva="0.00",
                    ttc="100.00",
                    date_emission=date(2026, 3, 10),
                    id_client=10,
                ),
                _facture(
                    numero="FAC-2",
                    ht="900.00",
                    tva="0.00",
                    ttc="900.00",
                    date_emission=date(2026, 3, 11),
                    id_client=11,
                ),
                _facture(
                    numero="FAC-3",
                    ht="500.00",
                    tva="0.00",
                    ttc="500.00",
                    date_emission=date(2026, 3, 12),
                    id_client=11,
                ),
                _facture(
                    numero="FAC-4",
                    ht="300.00",
                    tva="0.00",
                    ttc="300.00",
                    date_emission=date(2026, 3, 13),
                ),
            ],
        )
        lignes = session.execute(
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

    with Session(engine) as session:
        limitees = session.execute(
            statement_top_clients(
                id_entreprise=ENTREPRISE, devise="EUR", limite=1, **PERIODE
            )
        ).all()
    assert len(limitees) == 1
    assert limitees[0][0] == 11


def test_encours_et_montant_en_retard(engine: Engine) -> None:
    """Retard fondé sur la date d'échéance, encours excluant payées et annulées.

    Le statut ``en_retard`` du référentiel n'est jamais posé par l'API : un
    indicateur qui s'y fierait serait toujours nul.
    """
    with Session(engine) as session:
        _peupler(
            session,
            [
                # Échue et non soldée : en retard, et dans l'encours.
                _facture(
                    numero="FAC-RETARD",
                    ht="1000.00",
                    tva="0.00",
                    ttc="1000.00",
                    date_emission=date(2026, 3, 1),
                    date_echeance=date(2026, 4, 1),
                ),
                # Échéance à venir : dans l'encours seulement.
                _facture(
                    numero="FAC-A-VENIR",
                    ht="500.00",
                    tva="0.00",
                    ttc="500.00",
                    date_emission=date(2026, 7, 1),
                    date_echeance=date(2026, 9, 1),
                ),
                # Échue mais payée : ni retard, ni encours.
                _facture(
                    numero="FAC-PAYEE",
                    ht="700.00",
                    tva="0.00",
                    ttc="700.00",
                    date_emission=date(2026, 2, 1),
                    date_echeance=date(2026, 3, 1),
                    id_statut=STATUT_PAYEE,
                ),
                # Échue mais annulée : ni retard, ni encours.
                _facture(
                    numero="FAC-ANNULEE",
                    ht="300.00",
                    tva="0.00",
                    ttc="300.00",
                    date_emission=date(2026, 2, 2),
                    date_echeance=date(2026, 3, 2),
                    id_statut=STATUT_ANNULEE,
                ),
                # Sans échéance : jamais en retard, mais toujours dû.
                _facture(
                    numero="FAC-SANS-ECHEANCE",
                    ht="200.00",
                    tva="0.00",
                    ttc="200.00",
                    date_emission=date(2026, 3, 5),
                ),
            ],
        )
        ligne = session.execute(
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


def test_aucune_facture_agregats_nuls(engine: Engine) -> None:
    """Période vide : les SUM valent NULL en SQL, jamais une erreur."""
    with Session(engine) as session:
        _peupler(session, [])
        ligne = session.execute(
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
