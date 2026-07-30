"""Tests de la route de transmission à Chorus Pro.

Sans base de données ni réseau : session factice (mêmes doublures que les
autres tests factures) et client Chorus Pro remplacé par une doublure via
l'override de dépendance. Couvre le succès (colonnes renseignées, statut
``deposee_pdp``, événement PDP), les refus (brouillon, non conforme, déjà
transmise, hors périmètre, configuration absente) et l'échec de dépôt
(``codeRetour != 0`` → 502, statut ``erreur_transmission``).
"""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from src.auth.dependencies import get_current_user, verify_tenant_access
from src.core.config import settings
from src.core.database import get_session
from src.entreprises.models import Entreprise
from src.factures.models import (
    Facture,
    FactureLigne,
    StatutFacture,
    TauxTva,
)
from src.factures.router import get_chorus_client
from src.factures.router import router as factures_router
from src.integrations.chorus_pro.client import DepotFlux
from src.integrations.chorus_pro.exceptions import (
    ChorusProDepotError,
    ChorusProError,
)
from src.pdp.models import EvenementPdp
from src.utilisateurs.models import Utilisateur

ID_STATUT_VALIDEE = 2
ID_STATUT_ERREUR = 4
ID_STATUT_DEPOSEE = 5

STATUT_DEPOSEE = StatutFacture(id=ID_STATUT_DEPOSEE, libelle="deposee_pdp")
STATUT_ERREUR = StatutFacture(id=ID_STATUT_ERREUR, libelle="erreur_transmission")

DEPOT_OK = DepotFlux(
    numero_flux_depot="CPP0011117000000000414554",
    date_depot="2026-07-30",
    syntaxe_flux="IN_DP_E2_CII_FACTURX",
)


@pytest.fixture(autouse=True)
def _configuration_chorus(monkeypatch: pytest.MonkeyPatch) -> None:
    """Renseigne une configuration Chorus Pro complète (sandbox)."""
    monkeypatch.setattr(settings, "CHORUS_PISTE_CLIENT_ID", "client-id-test")
    monkeypatch.setattr(
        settings,
        "CHORUS_PISTE_CLIENT_SECRET",
        "client-secret-test",  # pragma: allowlist secret
    )
    monkeypatch.setattr(settings, "CHORUS_TECH_LOGIN", "TECH_1_test@cpro.fr")
    monkeypatch.setattr(
        settings,
        "CHORUS_TECH_PASSWORD",
        "mdp-technique",  # pragma: allowlist secret
    )
    monkeypatch.setattr(
        settings, "CHORUS_BASE_URL", "https://sandbox-api.piste.gouv.fr"
    )


class _Result:
    def __init__(self, value: Any) -> None:
        self._value = value

    def first(self) -> Any:
        return self._value


class _FakeSession:
    """Session factice : dépile des résultats, capture les add/commit."""

    def __init__(
        self, results: list[Any], gets: dict[tuple[Any, Any], Any] | None = None
    ) -> None:
        self._results = results
        self._gets = gets or {}
        self.added: list[Any] = []
        self.commits = 0

    async def exec(self, statement: Any) -> _Result:
        return _Result(self._results.pop(0))

    async def get(self, model: Any, key: Any) -> Any:
        return self._gets.get((model, key))

    def add(self, instance: Any) -> None:
        self.added.append(instance)

    async def commit(self) -> None:
        self.commits += 1


class _FakeChorusClient:
    """Doublure du client Chorus Pro : renvoie ou lève ce qu'on lui donne."""

    def __init__(self, resultat: DepotFlux | Exception) -> None:
        self._resultat = resultat
        self.appels: list[tuple[bytes, str]] = []

    async def deposer_flux_facturx(
        self, pdf_bytes: bytes, nom_fichier: str
    ) -> DepotFlux:
        self.appels.append((pdf_bytes, nom_fichier))
        if isinstance(self._resultat, Exception):
            raise self._resultat
        return self._resultat


# SIRET factices à clé de Luhn valide (mêmes doublures que les tests facturx).
def _entreprise() -> Entreprise:
    return Entreprise(id=1, nom_entreprise="Ma Boite SAS", siret="12345678900015")


def _facture_validee(
    statut: str = "validée",
    siret_emetteur: str | None = "12345678900015",
    numero_flux_depot_chorus: str | None = None,
) -> Facture:
    facture = Facture(
        id=42,
        id_entreprise=1,
        id_createur=1,
        id_client=7,
        numero_facture="FAC-202607-0001",
        date_emission=date(2026, 7, 30),
        date_echeance=date(2026, 8, 30),
        devise="EUR",
        id_statut=ID_STATUT_VALIDEE,
        siret_emetteur=siret_emetteur,
        siret_destinataire="98765432100023",
        snapshot_client={
            "raison_sociale": "Client Test SARL",
            "adresse": "1 rue de la Paix",
            "code_postal": "75002",
            "ville": "Paris",
        },
        total_ht=Decimal("100.00"),
        total_tva=Decimal("20.00"),
        total_ttc=Decimal("120.00"),
        numero_flux_depot_chorus=numero_flux_depot_chorus,
    )
    ligne = FactureLigne(
        id=1,
        id_facture=42,
        ordre=1,
        designation="Prestation de conseil",
        quantite=Decimal("2.000"),
        unite="jour",
        prix_unitaire_ht=Decimal("50.00"),
        id_taux_tva=4,
        montant_ht=Decimal("100.00"),
        montant_tva=Decimal("20.00"),
        montant_ttc=Decimal("120.00"),
    )
    ligne.taux_tva_ref = TauxTva(id=4, taux=Decimal("20.00"), libelle="Taux normal")
    facture.lignes = [ligne]
    facture.statut_ref = StatutFacture(id=ID_STATUT_VALIDEE, libelle=statut)
    return facture


def _app(session: _FakeSession, chorus_client: _FakeChorusClient) -> FastAPI:
    app = FastAPI()
    app.include_router(factures_router)
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_chorus_client] = lambda: chorus_client
    app.dependency_overrides[get_current_user] = lambda: Utilisateur(
        id=1,
        nom="Test",
        prenom="User",
        email="test@example.com",
        hash_mot_de_passe="x",  # pragma: allowlist secret
    )
    app.dependency_overrides[verify_tenant_access] = lambda: 1
    return app


async def _transmettre(
    session: _FakeSession, chorus_client: _FakeChorusClient
) -> Response:
    transport = ASGITransport(app=_app(session, chorus_client))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post("/factures/42/transmettre-choruspro")


def _session_complete(facture: Facture | None) -> _FakeSession:
    """Session servant la facture puis les deux statuts PDP du référentiel."""
    return _FakeSession(
        results=[facture, STATUT_DEPOSEE, STATUT_ERREUR],
        gets={(Entreprise, 1): _entreprise()},
    )


async def test_transmission_reussie() -> None:
    """Succès : 200, colonnes renseignées, statut deposee_pdp, événement PDP."""
    facture = _facture_validee()
    session = _session_complete(facture)
    chorus_client = _FakeChorusClient(DEPOT_OK)

    response = await _transmettre(session, chorus_client)

    assert response.status_code == 200
    assert response.json() == {
        "numero_flux_depot": "CPP0011117000000000414554",
        "date_depot": "2026-07-30",
        "syntaxe_flux": "IN_DP_E2_CII_FACTURX",
        "statut": "deposee_pdp",
    }

    # Le fichier envoyé est bien un PDF, sous le nom Factur-X de la facture.
    pdf_bytes, nom_fichier = chorus_client.appels[0]
    assert pdf_bytes.startswith(b"%PDF")
    assert nom_fichier == "FAC-202607-0001-facturx.pdf"

    # Traçage sur la facture et dans le journal PDP.
    assert facture.numero_flux_depot_chorus == "CPP0011117000000000414554"
    assert facture.date_transmission_chorus is not None
    assert facture.id_statut == ID_STATUT_DEPOSEE
    assert session.commits == 1
    evenements = [obj for obj in session.added if isinstance(obj, EvenementPdp)]
    assert len(evenements) == 1
    assert evenements[0].id_statut_avant == ID_STATUT_VALIDEE
    assert evenements[0].id_statut_apres == ID_STATUT_DEPOSEE
    assert evenements[0].source == "CHORUS_PRO_SANDBOX"
    assert "CPP0011117000000000414554" in (evenements[0].message or "")


async def test_echec_depot_code_retour_non_nul() -> None:
    """Rejet Chorus Pro : 502 avec le libellé, statut erreur_transmission."""
    facture = _facture_validee()
    session = _session_complete(facture)
    chorus_client = _FakeChorusClient(
        ChorusProDepotError(code_retour=135, libelle="Syntaxe de flux inconnue")
    )

    response = await _transmettre(session, chorus_client)

    assert response.status_code == 502
    assert "Syntaxe de flux inconnue" in response.json()["detail"]

    assert facture.numero_flux_depot_chorus is None
    assert facture.date_transmission_chorus is None
    assert facture.id_statut == ID_STATUT_ERREUR
    assert session.commits == 1
    evenements = [obj for obj in session.added if isinstance(obj, EvenementPdp)]
    assert len(evenements) == 1
    assert evenements[0].id_statut_apres == ID_STATUT_ERREUR


async def test_echec_technique_chorus() -> None:
    """Chorus Pro injoignable : 502, statut erreur_transmission."""
    facture = _facture_validee()
    session = _session_complete(facture)
    chorus_client = _FakeChorusClient(ChorusProError("Chorus Pro est injoignable."))

    response = await _transmettre(session, chorus_client)

    assert response.status_code == 502
    assert facture.id_statut == ID_STATUT_ERREUR
    assert facture.numero_flux_depot_chorus is None


async def test_refus_facture_non_conforme() -> None:
    """Non conforme (SIRET émetteur absent) : 409, aucun appel Chorus Pro."""
    session = _FakeSession(
        results=[_facture_validee(siret_emetteur=None)],
        gets={(Entreprise, 1): _entreprise()},
    )
    chorus_client = _FakeChorusClient(DEPOT_OK)

    response = await _transmettre(session, chorus_client)

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "non conforme" in detail["message"]
    assert any(erreur["code"] == "seller_siret_missing" for erreur in detail["erreurs"])
    assert chorus_client.appels == []


async def test_refus_brouillon() -> None:
    """Un brouillon ne peut pas être transmis : 409."""
    session = _FakeSession(results=[_facture_validee(statut="Brouillon")])
    chorus_client = _FakeChorusClient(DEPOT_OK)

    response = await _transmettre(session, chorus_client)

    assert response.status_code == 409
    assert "brouillon" in response.json()["detail"].lower()
    assert chorus_client.appels == []


async def test_refus_deja_transmise() -> None:
    """Déjà transmise avec succès : 409 (pas de double dépôt)."""
    session = _FakeSession(
        results=[_facture_validee(numero_flux_depot_chorus="CPP00111170000000004")]
    )
    chorus_client = _FakeChorusClient(DEPOT_OK)

    response = await _transmettre(session, chorus_client)

    assert response.status_code == 409
    assert "CPP00111170000000004" in response.json()["detail"]
    assert chorus_client.appels == []


async def test_facture_hors_perimetre_introuvable() -> None:
    """Facture inexistante ou d'une autre entreprise : 404 (isolation tenant)."""
    session = _FakeSession(results=[None])
    chorus_client = _FakeChorusClient(DEPOT_OK)

    response = await _transmettre(session, chorus_client)

    assert response.status_code == 404
    assert chorus_client.appels == []


async def test_configuration_absente(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sans credentials Chorus Pro : 503, aucun accès base ni réseau."""
    monkeypatch.setattr(settings, "CHORUS_PISTE_CLIENT_ID", None)
    session = _FakeSession(results=[])
    chorus_client = _FakeChorusClient(DEPOT_OK)

    response = await _transmettre(session, chorus_client)

    assert response.status_code == 503
    assert chorus_client.appels == []


async def test_referentiel_statuts_incomplet() -> None:
    """Statuts PDP absents du référentiel : 500 avant tout dépôt."""
    session = _FakeSession(
        results=[_facture_validee(), None, None],
        gets={(Entreprise, 1): _entreprise()},
    )
    chorus_client = _FakeChorusClient(DEPOT_OK)

    response = await _transmettre(session, chorus_client)

    assert response.status_code == 500
    assert chorus_client.appels == []
