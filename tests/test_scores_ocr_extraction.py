"""Tests de la réception et de la persistance des métadonnées d'analyse IA
(`type_document` et `par_champ`) transmises par le callback OCR.

Miroir côté API data de l'ajout additif au contrat de l'API IA : les champs
sont optionnels (rétrocompatibilité avec une API IA antérieure), les scores
par champ arrivent en chaînes et sont reparsés en Decimal, puis stockés en
chaînes sur l'extraction (précision préservée). Persistés en succès comme en
échec (un document refusé porte quand même un type détecté).

Sans base de données ni réseau : session factice qui sert les objets attendus
par le flux complet du webhook (document, taux, statut, facture, entreprise).
"""

from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError
from src.documents.models import Document, StatutExtraction
from src.documents.schemas import LigneOcr, OcrWebhookPayload
from src.documents.service import traiter_callback_ocr
from src.entreprises.models import Entreprise
from src.factures.models import Facture, StatutFacture, TauxTva

# Import nécessaire à la résolution des relations SQLAlchemy (mappers) :
# les modèles instanciés ici référencent Utilisateur et Client par nom.
from src.clients.models import Client  # noqa: F401  # isort: skip
from src.utilisateurs.models import Utilisateur  # noqa: F401  # isort: skip

PAR_CHAMP_CONTRAT = {
    "siret_emetteur": "0.9800",
    "siret_destinataire": "0.9500",
    "numero_facture": "0.9990",
    "date_emission": "0.8700",
    "total_ht": "0.9876",
    "total_tva": "0.9876",
    "total_ttc": "0.9876",
    "iban": "0.5000",
    "lignes": "0.9100",
}


class _Result:
    def __init__(self, value: Any) -> None:
        self._value = value

    def first(self) -> Any:
        return self._value

    def all(self) -> Any:
        return self._value


class _FakeSession:
    """Session factice : sert les `get` par classe de modèle et dépile les
    résultats de `exec` dans l'ordre des requêtes du flux webhook."""

    def __init__(self, get_map: dict[type, Any], exec_results: list[Any]) -> None:
        self._get_map = get_map
        self._exec_results = exec_results
        self.added: list[Any] = []
        self.commits = 0

    async def get(self, model: type, pk: Any) -> Any:
        return self._get_map.get(model)

    async def exec(self, statement: Any) -> _Result:
        return _Result(self._exec_results.pop(0))

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        pass

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, obj: Any) -> None:
        pass

    async def rollback(self) -> None:
        pass


def _session_flux_succes() -> _FakeSession:
    """Prépare le décor du flux webhook nominal (brouillon créé)."""
    document = Document(
        id=3,
        id_entreprise=1,
        id_utilisateur=1,
        nom_fichier="facture.pdf",
        nom_original="facture.pdf",
    )
    entreprise = Entreprise(id=1, siret="12345678900011")
    facture = Facture(
        id=77,
        id_entreprise=1,
        id_createur=1,
        numero_facture="BROUILLON-OCR77",
        id_statut=1,
        total_ht=Decimal("10.00"),
        total_tva=Decimal("2.00"),
        total_ttc=Decimal("12.00"),
    )
    taux = TauxTva(id=1, taux=Decimal("20.00"), libelle="TVA Normale 20%")
    statut_brouillon = StatutFacture(id=1, libelle="Brouillon")

    return _FakeSession(
        get_map={Document: document, Entreprise: entreprise},
        # Ordre des exec : taux actifs (mapping OCR), statut Brouillon,
        # taux des lignes (calcul), rechargement de la facture créée.
        exec_results=[[taux], statut_brouillon, [taux], facture],
    )


def _payload(
    *,
    lignes: list[LigneOcr] | None = None,
    **champs_additifs: Any,
) -> OcrWebhookPayload:
    if lignes is None:
        lignes = [
            LigneOcr(
                designation="Prestation",
                prix_unitaire_ht=Decimal("10.00"),
                taux_tva=Decimal("20.00"),
            )
        ]
    return OcrWebhookPayload(
        id_document=3,
        score_confiance=Decimal("0.95"),
        total_ht=Decimal("10.00"),
        total_tva=Decimal("2.00"),
        total_ttc=Decimal("12.00"),
        lignes=lignes,
        **champs_additifs,
    )


async def test_succes_persiste_type_document_et_par_champ() -> None:
    """Flux nominal : l'extraction en succès porte le type détecté et les
    scores par champ, stockés en chaînes telles que reçues du contrat."""
    session = _session_flux_succes()
    payload = _payload(
        type_document="facture",
        par_champ={champ: Decimal(score) for champ, score in PAR_CHAMP_CONTRAT.items()},
    )
    extraction = await traiter_callback_ocr(session, payload)  # type: ignore[arg-type]

    assert extraction.statut == StatutExtraction.SUCCES
    assert extraction.type_document == "facture"
    assert extraction.par_champ == PAR_CHAMP_CONTRAT


async def test_echec_persiste_type_document_et_par_champ() -> None:
    """Échec (aucune ligne exploitable) : l'extraction en échec conserve
    quand même le type détecté et les scores transmis."""
    session = _FakeSession(
        get_map={
            Document: Document(
                id=3,
                id_entreprise=1,
                id_utilisateur=1,
                nom_fichier="devis.pdf",
                nom_original="devis.pdf",
            )
        },
        exec_results=[],
    )
    payload = _payload(
        lignes=[],
        type_document="devis",
        par_champ={"siret_emetteur": Decimal("0.9800")},
    )
    extraction = await traiter_callback_ocr(session, payload)  # type: ignore[arg-type]

    assert extraction.statut == StatutExtraction.ECHEC
    assert extraction.type_document == "devis"
    assert extraction.par_champ == {"siret_emetteur": "0.9800"}


async def test_retrocompat_sans_les_nouveaux_champs() -> None:
    """Callback d'une API IA antérieure (sans les champs additifs) : accepté,
    métadonnées à null sur l'extraction (non calculé)."""
    session = _session_flux_succes()
    extraction = await traiter_callback_ocr(session, _payload())  # type: ignore[arg-type]

    assert extraction.statut == StatutExtraction.SUCCES
    assert extraction.type_document is None
    assert extraction.par_champ is None


def test_champ_inconnu_ignore() -> None:
    """Un champ non prévu au contrat est ignoré (extra='ignore' par défaut) :
    aucune fenêtre de 422 pendant un déploiement échelonné de l'API IA."""
    payload = OcrWebhookPayload.model_validate(
        {
            "id_document": 3,
            "score_confiance": "0.95",
            "total_ht": "10.00",
            "total_tva": "2.00",
            "total_ttc": "12.00",
            "champ_mystere": "surprise",
        }
    )
    assert not hasattr(payload, "champ_mystere")


def test_par_champ_chaines_reparsees_en_decimal() -> None:
    """Les scores du contrat arrivent en chaînes « 0 »–« 1 » à 4 décimales :
    reparsés en Decimal exact à la réception, clés non contraintes (un champ
    scoré de plus par l'IA est accepté)."""
    payload = OcrWebhookPayload.model_validate(
        {
            "id_document": 3,
            "score_confiance": "0.95",
            "total_ht": "10.00",
            "total_tva": "2.00",
            "total_ttc": "12.00",
            "type_document": "avoir",
            "par_champ": {"total_ht": "0.9876", "champ_futur": "0.1234"},
        }
    )
    assert payload.type_document == "avoir"
    assert payload.par_champ == {
        "total_ht": Decimal("0.9876"),
        "champ_futur": Decimal("0.1234"),
    }


def test_type_document_hors_contrat_refuse() -> None:
    """Miroir strict du contrat : une 5e valeur non coordonnée de
    `type_document` est refusée (signal de désynchronisation souhaité)."""
    with pytest.raises(ValidationError):
        OcrWebhookPayload.model_validate(
            {
                "id_document": 3,
                "score_confiance": "0.95",
                "total_ht": "10.00",
                "total_tva": "2.00",
                "total_ttc": "12.00",
                "type_document": "bon_de_commande",
            }
        )
