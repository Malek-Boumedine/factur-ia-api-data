"""Non-régression : suspension et réactivation d'une entreprise par la plateforme.

Vérifie les deux propriétés attendues de ces opérations :

- **action inter-entreprise** : l'administrateur agit sur une entreprise ciblée
  par son identifiant, sans en être membre et sans header tenant — c'est tout
  l'objet de ce périmètre ;
- **cohérence transactionnelle** : suspendre coupe l'accès *et* bascule la
  souscription en un seul commit, de sorte qu'aucun état intermédiaire (accès
  coupé mais abonnement toujours actif, ou l'inverse) ne puisse être observé.

La réactivation doit par ailleurs toujours rendre l'entreprise à un abonnement
actif, y compris après une résiliation.
"""

from typing import Any

import pytest
from src.abonnements import services as abonnements_services
from src.abonnements.models import Abonnement, EntrepriseAbonnement, StatutSouscription
from src.administration import services
from src.entreprises.models import Entreprise

_ENTREPRISE_ID = 42


class _FakeSession:
    """Session factice enregistrant les objets ajoutés et les commits."""

    def __init__(self, entreprise: Entreprise | None) -> None:
        self._entreprise = entreprise
        self.ajoutes: list[Any] = []
        self.commits = 0

    async def get(self, modele: type, identifiant: int) -> Any:
        if identifiant == _ENTREPRISE_ID:
            return self._entreprise
        return None

    def add(self, objet: Any) -> None:
        self.ajoutes.append(objet)

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, objet: Any) -> None:
        return None


def _entreprise(est_actif: bool = True) -> Entreprise:
    return Entreprise(id=_ENTREPRISE_ID, nom_entreprise="ACME", est_actif=est_actif)


def _souscription(statut: StatutSouscription) -> EntrepriseAbonnement:
    return EntrepriseAbonnement(
        id=7, id_entreprise=_ENTREPRISE_ID, id_abonnement=3, statut=statut
    )


def _preparer_souscription(
    monkeypatch: pytest.MonkeyPatch, souscription: EntrepriseAbonnement | None
) -> None:
    """Fixe la souscription courante renvoyée par le service."""

    async def _courante(
        session: Any, entreprise_id: int
    ) -> EntrepriseAbonnement | None:
        return souscription

    monkeypatch.setattr(services, "_souscription_courante", _courante)


async def test_suspension_coupe_l_acces_et_l_abonnement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Suspendre bascule l'entreprise ET sa souscription en un seul commit : les
    deux effets sont indissociables.
    """
    souscription = _souscription(StatutSouscription.ACTIF)
    _preparer_souscription(monkeypatch, souscription)
    entreprise = _entreprise()
    session = _FakeSession(entreprise)

    resultat = await services.suspendre_entreprise(
        session,  # type: ignore[arg-type]
        _ENTREPRISE_ID,
        "Impayé récurrent",
    )

    assert resultat.est_actif is False
    assert resultat.motif_suspension == "Impayé récurrent"
    assert resultat.date_suspension is not None
    assert souscription.statut == StatutSouscription.SUSPENDU
    assert session.commits == 1


async def test_suspension_agit_sur_une_entreprise_non_membre(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    L'entreprise est désignée par son seul identifiant : aucun rattachement de
    l'administrateur n'est consulté, et aucun header tenant n'intervient.
    """
    _preparer_souscription(monkeypatch, _souscription(StatutSouscription.ACTIF))
    session = _FakeSession(_entreprise())

    resultat = await services.suspendre_entreprise(session, _ENTREPRISE_ID, None)  # type: ignore[arg-type]

    assert resultat.id == _ENTREPRISE_ID
    assert resultat.est_actif is False


async def test_reactivation_retablit_acces_et_abonnement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Réactiver rend l'accès et repasse la souscription suspendue en actif."""
    souscription = _souscription(StatutSouscription.SUSPENDU)
    _preparer_souscription(monkeypatch, souscription)
    session = _FakeSession(_entreprise(est_actif=False))

    resultat = await services.reactiver_entreprise(session, _ENTREPRISE_ID)  # type: ignore[arg-type]

    assert resultat.est_actif is True
    assert resultat.date_suspension is None
    assert resultat.motif_suspension is None
    assert souscription.statut == StatutSouscription.ACTIF
    assert session.commits == 1


async def test_reactivation_apres_resiliation_rouvre_un_plan_gratuit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Une souscription résiliée ne se « dé-résilie » pas : la réactivation ouvre
    une nouvelle souscription au plan gratuit, pour qu'une entreprise en service
    ait toujours un abonnement actif.
    """
    _preparer_souscription(monkeypatch, _souscription(StatutSouscription.ANNULE))

    async def _plan_gratuit(session: Any) -> Abonnement:
        return Abonnement(id=1, libelle="GRATUITE")

    monkeypatch.setattr(abonnements_services, "resoudre_plan_gratuit", _plan_gratuit)
    session = _FakeSession(_entreprise(est_actif=False))

    resultat = await services.reactiver_entreprise(session, _ENTREPRISE_ID)  # type: ignore[arg-type]

    assert resultat.est_actif is True
    nouvelles = [
        objet for objet in session.ajoutes if isinstance(objet, EntrepriseAbonnement)
    ]
    assert len(nouvelles) == 1
    assert nouvelles[0].statut == StatutSouscription.ACTIF
    assert nouvelles[0].id_abonnement == 1


async def test_resiliation_coupe_aussi_l_acces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Résilier clôt la relation commerciale et coupe l'accès : une entreprise sans
    abonnement actif ne doit pas continuer à utiliser le service.
    """
    souscription = _souscription(StatutSouscription.ACTIF)
    _preparer_souscription(monkeypatch, souscription)
    entreprise = _entreprise()
    session = _FakeSession(entreprise)

    resultat = await services.resilier_abonnement(session, _ENTREPRISE_ID, None)  # type: ignore[arg-type]

    assert resultat.statut == StatutSouscription.ANNULE
    assert resultat.date_fin is not None
    assert entreprise.est_actif is False
    assert session.commits == 1
