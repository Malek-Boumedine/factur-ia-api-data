"""Tests de la réception et de la propagation de la date d'échéance extraite
par l'OCR jusqu'au brouillon de facture.

Miroir côté API data de l'ajout au contrat de l'API IA : `date_echeance` est
reçue comme `date_emission` (date ISO coercée par Pydantic), optionnelle
(rétrocompatibilité avec une API IA antérieure), et transmise telle quelle au
brouillon — sans valeur par défaut, contrairement à l'émission : la colonne
est nullable, une échéance absente vaut mieux qu'une date inventée. Aucune
validation ne rejette une échéance future ou incohérente : le brouillon est un
état de travail, corrigé à la main avant validation.

Sans base de données ni réseau : session factice qui sert les objets attendus
par le flux complet du webhook (document, taux, statut, facture, entreprise).
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from src.documents.models import Document
from src.documents.schemas import LigneOcr, OcrWebhookPayload
from src.documents.service import traiter_callback_ocr
from src.entreprises.models import Entreprise
from src.factures.models import Facture, StatutFacture, TauxTva
from src.factures.schemas import FactureRead

# Import nécessaire à la résolution des relations SQLAlchemy (mappers) :
# les modèles instanciés ici référencent Utilisateur et Client par nom.
from src.clients.models import Client  # noqa: F401  # isort: skip
from src.utilisateurs.models import Utilisateur  # noqa: F401  # isort: skip


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

    async def get(self, model: type, pk: Any) -> Any:
        return self._get_map.get(model)

    async def exec(self, statement: Any) -> _Result:
        return _Result(self._exec_results.pop(0))

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        pass

    async def commit(self) -> None:
        pass

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


def _payload(**champs: Any) -> OcrWebhookPayload:
    return OcrWebhookPayload(
        id_document=3,
        score_confiance=Decimal("0.95"),
        total_ht=Decimal("10.00"),
        total_tva=Decimal("2.00"),
        total_ttc=Decimal("12.00"),
        lignes=[
            LigneOcr(
                designation="Prestation",
                prix_unitaire_ht=Decimal("10.00"),
                taux_tva=Decimal("20.00"),
            )
        ],
        **champs,
    )


def _brouillon_cree(session: _FakeSession) -> Facture:
    """Récupère le brouillon construit par le service dans la session.

    Le rechargement post-commit renvoie la facture factice du décor : c'est
    l'objet ajouté à la session qui porte les valeurs réellement écrites.
    """
    brouillons = [obj for obj in session.added if isinstance(obj, Facture)]
    assert len(brouillons) == 1
    return brouillons[0]


async def test_echeance_recue_persistee_sur_le_brouillon() -> None:
    """Une échéance extraite par l'IA est écrite telle quelle sur le brouillon."""
    session = _session_flux_succes()
    payload = _payload(date_emission=date(2026, 3, 15), date_echeance=date(2026, 4, 30))

    await traiter_callback_ocr(session, payload)  # type: ignore[arg-type]

    brouillon = _brouillon_cree(session)
    assert brouillon.date_emission == date(2026, 3, 15)
    assert brouillon.date_echeance == date(2026, 4, 30)


async def test_retrocompat_sans_echeance() -> None:
    """Callback d'une API IA antérieure (sans `date_echeance`) : accepté, le
    brouillon sort avec une échéance nulle, à saisir à la main."""
    session = _session_flux_succes()

    await traiter_callback_ocr(session, _payload())  # type: ignore[arg-type]

    assert _brouillon_cree(session).date_echeance is None


async def test_echeance_posterieure_a_emission_acceptee() -> None:
    """Cas nominal métier (échéance à 30 jours) : aucune validation croisée ne
    rejette une échéance future, le brouillon prend la date telle qu'extraite."""
    session = _session_flux_succes()
    payload = _payload(date_emission=date(2026, 3, 15), date_echeance=date(2027, 1, 1))

    await traiter_callback_ocr(session, payload)  # type: ignore[arg-type]

    brouillon = _brouillon_cree(session)
    assert brouillon.date_echeance is not None
    assert brouillon.date_echeance > brouillon.date_emission


def test_echeance_iso_coercee_et_champ_inconnu_ignore() -> None:
    """Réception : date ISO « AAAA-MM-JJ » coercée en `date` comme l'émission,
    et champ hors contrat ignoré (extra='ignore') — aucune fenêtre de 422
    pendant un déploiement échelonné de l'API IA."""
    payload = OcrWebhookPayload.model_validate(
        {
            "id_document": 3,
            "score_confiance": "0.95",
            "total_ht": "10.00",
            "total_tva": "2.00",
            "total_ttc": "12.00",
            "date_emission": "2026-03-15",
            "date_echeance": "2026-04-30",
            "champ_mystere": "surprise",
        }
    )
    assert payload.date_emission == date(2026, 3, 15)
    assert payload.date_echeance == date(2026, 4, 30)
    assert not hasattr(payload, "champ_mystere")


def test_echeance_exposee_en_lecture() -> None:
    """L'échéance persistée est relue et sérialisée par `FactureRead`."""
    facture = Facture(
        id=77,
        id_entreprise=1,
        id_createur=1,
        numero_facture="BROUILLON-OCR77",
        id_statut=1,
        date_emission=date(2026, 3, 15),
        date_echeance=date(2026, 4, 30),
        total_ht=Decimal("10.00"),
        total_tva=Decimal("2.00"),
        total_ttc=Decimal("12.00"),
        date_creation=datetime(2026, 3, 15, 9, 0, 0),
    )

    lecture = FactureRead.model_validate(facture)

    assert lecture.date_echeance == date(2026, 4, 30)
    assert lecture.model_dump(mode="json")["date_echeance"] == "2026-04-30"
