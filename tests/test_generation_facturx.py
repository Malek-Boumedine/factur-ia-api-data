"""Tests de la génération du fichier Factur-X (PDF/A-3 + XML CII MINIMUM).

Sans base de données ni réseau : mêmes doublures que les autres tests
factures, et validation XSD contre les schémas embarqués dans la librairie
``factur-x``. Couvre le round-trip complet (le XML ressort du PDF et valide
le XSD MINIMUM), la structure PDF/A-3 (pièce jointe ``factur-x.xml``, clé
``/AF``, métadonnées XMP), le contenu (numéro, totaux, TypeCode 380/381) et
les garde-fous : 409 sur brouillon, 404 hors périmètre entreprise, 409 si le
SIRET émetteur manque.
"""

import io
import re
from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from lxml import etree
from pypdf import PdfReader
from src.auth.dependencies import get_current_user, verify_tenant_access
from src.core.database import get_session
from src.entreprises.models import Entreprise
from src.factures.models import (
    Facture,
    FactureLigne,
    StatutFacture,
    TauxTva,
    TypeFacture,
)
from src.factures.router import router as factures_router
from src.utilisateurs.models import Utilisateur

from facturx import get_facturx_xml_from_pdf, xml_check_xsd

NAMESPACES = {
    "rsm": "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100",
    "ram": (
        "urn:un:unece:uncefact:data:standard:"
        "ReusableAggregateBusinessInformationEntity:100"
    ),
    "udt": "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100",
}


class _Result:
    def __init__(self, value: Any) -> None:
        self._value = value

    def first(self) -> Any:
        return self._value


class _FakeSession:
    """Session factice : dépile des résultats prévus et sert les ``get``."""

    def __init__(
        self, results: list[Any], gets: dict[tuple[Any, Any], Any] | None = None
    ) -> None:
        self._results = results
        self._gets = gets or {}

    async def exec(self, statement: Any) -> _Result:
        return _Result(self._results.pop(0))

    async def get(self, model: Any, key: Any) -> Any:
        return self._gets.get((model, key))


# SIRET factices à clé de Luhn valide : la génération applique les règles de
# conformité (check_facturx_minimum) et refuserait un SIRET à clé invalide.
def _entreprise() -> Entreprise:
    return Entreprise(id=1, nom_entreprise="Ma Boite SAS", siret="12345678900015")


def _facture_validee(
    statut: str = "validée",
    type_facture: TypeFacture = TypeFacture.FACTURE,
    siret_emetteur: str | None = "12345678900015",
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
        type_facture=type_facture,
        id_statut=2,
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
        mode_paiement="Virement",
        iban="FR7630006000011234567890189",
        reference_commande="CMD-001",
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
    facture.statut_ref = StatutFacture(id=2, libelle=statut)
    return facture


def _app(session: _FakeSession) -> FastAPI:
    app = FastAPI()
    app.include_router(factures_router)
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: Utilisateur(
        id=1,
        nom="Test",
        prenom="User",
        email="test@example.com",
        hash_mot_de_passe="x",  # pragma: allowlist secret
    )
    app.dependency_overrides[verify_tenant_access] = lambda: 1
    return app


async def _telecharger(facture: Facture | None) -> Response:
    """Appelle la route de téléchargement avec une facture (ou None = 404)."""
    session = _FakeSession(results=[facture], gets={(Entreprise, 1): _entreprise()})
    transport = ASGITransport(app=_app(session))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get("/factures/42/facturx")


def _xpath_text(xml_root: Any, path: str) -> str:
    elements = xml_root.findall(path, NAMESPACES)
    assert len(elements) == 1, f"attendu 1 élément pour {path}, trouvé {len(elements)}"
    return str(elements[0].text)


async def test_telechargement_facturx_round_trip() -> None:
    """Facture validée : 200, PDF en pièce jointe, XML CII conforme au XSD."""
    response = await _telecharger(_facture_validee())

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert (
        response.headers["content-disposition"]
        == 'attachment; filename="FAC-202607-0001-facturx.pdf"'
    )

    # Round-trip : le XML ressort du PDF et valide le XSD MINIMUM embarqué
    # dans la librairie (aucun appel réseau).
    filename, xml_bytes = get_facturx_xml_from_pdf(
        io.BytesIO(response.content), check_xsd=True
    )
    assert filename == "factur-x.xml"
    xml_check_xsd(xml_bytes, flavor="factur-x", level="minimum")

    root = etree.fromstring(xml_bytes)
    assert _xpath_text(root, ".//rsm:ExchangedDocument/ram:ID") == "FAC-202607-0001"
    assert _xpath_text(root, ".//rsm:ExchangedDocument/ram:TypeCode") == "380"
    assert (
        _xpath_text(root, ".//ram:GuidelineSpecifiedDocumentContextParameter/ram:ID")
        == "urn:factur-x.eu:1p0:minimum"
    )
    assert _xpath_text(root, ".//ram:SellerTradeParty/ram:Name") == "Ma Boite SAS"
    assert (
        _xpath_text(
            root, ".//ram:SellerTradeParty/ram:PostalTradeAddress/ram:CountryID"
        )
        == "FR"
    )
    assert _xpath_text(root, ".//ram:BuyerTradeParty/ram:Name") == "Client Test SARL"
    assert _xpath_text(root, ".//ram:TaxBasisTotalAmount") == "100.00"
    assert _xpath_text(root, ".//ram:TaxTotalAmount") == "20.00"
    assert _xpath_text(root, ".//ram:GrandTotalAmount") == "120.00"
    assert _xpath_text(root, ".//ram:DuePayableAmount") == "120.00"

    # Identifiants légaux : SIRET avec le schéma ICD 0009
    seller_id = root.findall(
        ".//ram:SellerTradeParty/ram:SpecifiedLegalOrganization/ram:ID", NAMESPACES
    )[0]
    assert seller_id.text == "12345678900015"
    assert seller_id.get("schemeID") == "0009"

    # Date au format CII 102 (AAAAMMJJ)
    assert _xpath_text(root, ".//udt:DateTimeString") == "20260730"


async def test_structure_pdfa3() -> None:
    """Le PDF porte les marqueurs PDF/A-3 : /AF, pièce jointe, XMP pdfaid."""
    response = await _telecharger(_facture_validee())
    assert response.status_code == 200

    reader = PdfReader(io.BytesIO(response.content))
    root = reader.trailer["/Root"]
    assert "/AF" in root
    assert list(reader.attachments.keys()) == ["factur-x.xml"]

    xmp = root["/Metadata"].get_data()
    assert b"<pdfaid:part>3</pdfaid:part>" in xmp
    assert b"<pdfaid:conformance>B</pdfaid:conformance>" in xmp
    assert re.search(rb"<fx:ConformanceLevel>MINIMUM</fx:ConformanceLevel>", xmp)
    assert b"<fx:DocumentFileName>factur-x.xml</fx:DocumentFileName>" in xmp


async def test_avoir_type_code_381() -> None:
    """Un avoir produit un TypeCode CII 381 (au lieu de 380)."""
    facture = _facture_validee(type_facture=TypeFacture.AVOIR)
    # Les avoirs sont stockés en montants négatifs (règle de signe vérifiée
    # par la conformité).
    facture.total_ht = -facture.total_ht
    facture.total_tva = -facture.total_tva
    facture.total_ttc = -facture.total_ttc
    response = await _telecharger(facture)
    assert response.status_code == 200

    _, xml_bytes = get_facturx_xml_from_pdf(io.BytesIO(response.content))
    root = etree.fromstring(xml_bytes)
    assert _xpath_text(root, ".//rsm:ExchangedDocument/ram:TypeCode") == "381"


async def test_statut_famille_validee_telechargeable() -> None:
    """Une facture payée (famille validée) reste téléchargeable."""
    response = await _telecharger(_facture_validee(statut="payee"))
    assert response.status_code == 200


async def test_refus_brouillon() -> None:
    """Un brouillon n'a pas de Factur-X : refus 409."""
    response = await _telecharger(_facture_validee(statut="Brouillon"))
    assert response.status_code == 409
    assert "brouillon" in response.json()["detail"].lower()


async def test_facture_hors_perimetre_introuvable() -> None:
    """Facture inexistante ou d'une autre entreprise : 404 (isolation tenant)."""
    response = await _telecharger(None)
    assert response.status_code == 404


async def test_siret_emetteur_manquant() -> None:
    """SIRET émetteur absent : donnée obligatoire du XML, refus 409 explicite."""
    response = await _telecharger(_facture_validee(siret_emetteur=None))
    assert response.status_code == 409
    assert "SIRET" in response.json()["detail"]


async def test_iban_complet_sur_le_pdf() -> None:
    """L'IBAN figure en entier sur le PDF (mention de paiement), jamais masqué.

    C'est le seul canal légitime pour l'IBAN complet : les lectures API le
    masquent, mais la facture émise doit porter les coordonnées de règlement.
    """
    response = await _telecharger(_facture_validee())
    assert response.status_code == 200

    reader = PdfReader(io.BytesIO(response.content))
    texte = "".join(page.extract_text() for page in reader.pages)
    assert "FR7630006000011234567890189" in texte.replace(" ", "")
    assert "•" not in texte
