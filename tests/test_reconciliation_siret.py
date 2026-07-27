"""Tests de la réconciliation du SIRET émetteur à la création du brouillon OCR.

Règle métier : l'émetteur d'une facture est toujours l'entreprise détentrice
de l'abonnement. À la création du brouillon par le webhook (`traiter_callback_ocr`) :
SIRET extrait vide → celui de l'entreprise ; sinon la valeur lue est conservée
(identique ou divergente — le front compare et signale). La validation reste
l'autorité qui écrase toujours depuis l'entreprise.

Sans base de données ni réseau : session factice qui sert les objets attendus
par le flux complet du webhook (document, taux, statut, facture, entreprise).
"""

from decimal import Decimal
from typing import Any

from src.documents.models import Document, StatutDocument, StatutExtraction
from src.documents.schemas import LigneOcr, OcrWebhookPayload
from src.documents.service import traiter_callback_ocr
from src.entreprises.models import Entreprise
from src.factures.models import Facture, StatutFacture, TauxTva

# Import nécessaire à la résolution des relations SQLAlchemy (mappers) :
# les modèles instanciés ici référencent Utilisateur et Client par nom.
from src.clients.models import Client  # noqa: F401  # isort: skip
from src.utilisateurs.models import Utilisateur  # noqa: F401  # isort: skip

SIRET_ENTREPRISE = "12345678900011"
SIRET_DIVERGENT = "99999999900099"
SIRET_DESTINATAIRE = "83281075800025"


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


def _setup(
    *,
    siret_extrait: str | None,
    siret_entreprise: str | None = SIRET_ENTREPRISE,
    siret_destinataire_extrait: str | None = None,
) -> tuple[_FakeSession, OcrWebhookPayload, Facture]:
    """Prépare le décor du flux webhook complet, paramétré par les SIRET."""
    document = Document(
        id=3,
        id_entreprise=1,
        id_utilisateur=1,
        nom_fichier="facture.pdf",
        nom_original="facture.pdf",
    )
    entreprise = Entreprise(id=1, siret=siret_entreprise)
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

    session = _FakeSession(
        get_map={Document: document, Entreprise: entreprise},
        # Ordre des exec : taux actifs (mapping OCR), statut Brouillon,
        # taux des lignes (calcul), rechargement de la facture créée.
        exec_results=[[taux], statut_brouillon, [taux], facture],
    )
    payload = OcrWebhookPayload(
        id_document=3,
        score_confiance=Decimal("0.95"),
        siret_emetteur=siret_extrait,
        siret_destinataire=siret_destinataire_extrait,
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
    )
    return session, payload, facture


async def test_siret_extrait_vide_renseigne_depuis_entreprise() -> None:
    """OCR muet sur le SIRET : le brouillon propose celui de l'entreprise."""
    session, payload, facture = _setup(siret_extrait=None)
    extraction = await traiter_callback_ocr(session, payload)  # type: ignore[arg-type]

    assert facture.siret_emetteur == SIRET_ENTREPRISE
    # Le flux nominal reste intact : extraction en succès, liée au brouillon
    assert extraction.statut == StatutExtraction.SUCCES
    assert extraction.id_facture == 77


async def test_siret_extrait_identique_garde() -> None:
    """SIRET lu identique à celui de l'entreprise : conservé tel quel."""
    session, payload, facture = _setup(siret_extrait=SIRET_ENTREPRISE)
    await traiter_callback_ocr(session, payload)  # type: ignore[arg-type]

    assert facture.siret_emetteur == SIRET_ENTREPRISE


async def test_siret_extrait_divergent_conserve() -> None:
    """SIRET lu différent : la valeur extraite est conservée sur le brouillon.

    C'est le front qui compare `siret_emetteur` au SIRET de l'entreprise et
    alerte l'utilisateur (probable erreur d'OCR). La règle métier reste
    garantie : la validation écrasera depuis l'entreprise.
    """
    session, payload, facture = _setup(siret_extrait=SIRET_DIVERGENT)
    await traiter_callback_ocr(session, payload)  # type: ignore[arg-type]

    assert facture.siret_emetteur == SIRET_DIVERGENT


async def test_callback_avec_deux_siret_produit_brouillon_avec_les_deux() -> None:
    """Un callback portant les deux SIRET produit un brouillon qui les porte.

    On vérifie la facture réellement créée par `create_facture_brouillon`
    (celle ajoutée à la session) : c'est elle qui est persistée en base.
    """
    session, payload, _ = _setup(
        siret_extrait=SIRET_DIVERGENT,
        siret_destinataire_extrait=SIRET_DESTINATAIRE,
    )
    await traiter_callback_ocr(session, payload)  # type: ignore[arg-type]

    brouillon = [obj for obj in session.added if isinstance(obj, Facture)][0]
    assert brouillon.siret_emetteur == SIRET_DIVERGENT
    assert brouillon.siret_destinataire == SIRET_DESTINATAIRE


async def test_entreprise_sans_siret_reste_none() -> None:
    """Entreprise sans SIRET et OCR muet : le brouillon reste sans émetteur."""
    session, payload, facture = _setup(siret_extrait=None, siret_entreprise=None)
    extraction = await traiter_callback_ocr(session, payload)  # type: ignore[arg-type]

    assert facture.siret_emetteur is None
    # Le document est bien passé en TRAITE malgré l'absence de SIRET
    document = [obj for obj in session.added if isinstance(obj, Document)][0]
    assert document.statut == StatutDocument.TRAITE
    assert extraction.statut == StatutExtraction.SUCCES
