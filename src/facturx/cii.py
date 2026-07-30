"""Construction du XML CII (Cross Industry Invoice) au profil Factur-X MINIMUM.

Le profil MINIMUM (norme EN 16931, guideline ``urn:factur-x.eu:1p0:minimum``)
ne porte que l'en-tête de la facture : identité des parties, totaux, devise.
Les lignes, l'IBAN et les conditions de paiement figurent uniquement sur le
PDF visuel. C'est le profil couvert par les données actuellement en base ;
l'upgrade vers BASIC/EN 16931 nécessite d'ajouter l'adresse et le numéro de
TVA de l'entreprise émettrice, puis d'enrichir le snapshot client.
"""

from decimal import Decimal
from typing import Any

from lxml import etree

from src.entreprises.models import Entreprise
from src.factures.models import Facture, TypeFacture
from src.facturx.exceptions import DonneesFacturXManquantesError

NS_RSM = "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"
NS_RAM = (
    "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100"
)
NS_UDT = "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100"
NSMAP = {"rsm": NS_RSM, "ram": NS_RAM, "udt": NS_UDT}

GUIDELINE_MINIMUM = "urn:factur-x.eu:1p0:minimum"
# Identifiant de processus métier (BT-23) utilisé par les exemples officiels
# Factur-X pour le cadre de facturation français.
BUSINESS_PROCESS = "A1"
# Aucun code pays en base : émetteur français assumé (limite documentée du MVP).
CODE_PAYS_DEFAUT = "FR"
# ICD 0009 = SIRET (l'identifiant légal stocké en base fait 14 chiffres).
SCHEME_ID_SIRET = "0009"

TYPE_CODE_FACTURE = "380"
TYPE_CODE_AVOIR = "381"


def _amount(value: Decimal) -> str:
    """Formate un montant en chaîne à 2 décimales (exigence des types CII)."""
    return str(value.quantize(Decimal("0.01")))


def _el(
    parent: Any, namespace: str, tag: str, text: str | None = None, **attrs: str
) -> Any:
    """Ajoute un sous-élément namespacé et renvoie l'élément créé."""
    element = etree.SubElement(parent, f"{{{namespace}}}{tag}")
    if text is not None:
        element.text = text
    for key, value in attrs.items():
        element.set(key, value)
    return element


def build_cii_minimum_xml(facture: Facture, entreprise: Entreprise) -> bytes:
    """Construit le XML CII au profil MINIMUM depuis une facture validée.

    Les identités des parties proviennent des snapshots figés à la validation
    (SIRET, raison sociale du client) ; seul le nom de l'émetteur est lu sur
    la fiche entreprise courante, faute d'être snapshoté.
    """
    manquants: list[str] = []
    if not facture.siret_emetteur:
        manquants.append("SIRET de l'émetteur")
    snapshot = facture.snapshot_client or {}
    raison_sociale_client = snapshot.get("raison_sociale")
    if not raison_sociale_client:
        manquants.append("raison sociale du destinataire (snapshot client)")
    if manquants:
        raise DonneesFacturXManquantesError(
            "Impossible de générer le fichier Factur-X, données obligatoires "
            f"manquantes : {', '.join(manquants)}."
        )

    root = etree.Element(f"{{{NS_RSM}}}CrossIndustryInvoice", nsmap=NSMAP)

    # rsm:ExchangedDocumentContext — profil et processus métier
    contexte = _el(root, NS_RSM, "ExchangedDocumentContext")
    processus = _el(
        contexte, NS_RAM, "BusinessProcessSpecifiedDocumentContextParameter"
    )
    _el(processus, NS_RAM, "ID", BUSINESS_PROCESS)
    guideline = _el(contexte, NS_RAM, "GuidelineSpecifiedDocumentContextParameter")
    _el(guideline, NS_RAM, "ID", GUIDELINE_MINIMUM)

    # rsm:ExchangedDocument — numéro, type, date d'émission
    document = _el(root, NS_RSM, "ExchangedDocument")
    _el(document, NS_RAM, "ID", facture.numero_facture)
    type_code = (
        TYPE_CODE_AVOIR
        if facture.type_facture == TypeFacture.AVOIR
        else TYPE_CODE_FACTURE
    )
    _el(document, NS_RAM, "TypeCode", type_code)
    date_emission = _el(document, NS_RAM, "IssueDateTime")
    _el(
        date_emission,
        NS_UDT,
        "DateTimeString",
        facture.date_emission.strftime("%Y%m%d"),
        format="102",
    )

    # rsm:SupplyChainTradeTransaction
    transaction = _el(root, NS_RSM, "SupplyChainTradeTransaction")

    # ram:ApplicableHeaderTradeAgreement — émetteur et destinataire
    agreement = _el(transaction, NS_RAM, "ApplicableHeaderTradeAgreement")
    vendeur = _el(agreement, NS_RAM, "SellerTradeParty")
    _el(vendeur, NS_RAM, "Name", entreprise.nom_entreprise)
    organisation_vendeur = _el(vendeur, NS_RAM, "SpecifiedLegalOrganization")
    _el(
        organisation_vendeur,
        NS_RAM,
        "ID",
        facture.siret_emetteur,
        schemeID=SCHEME_ID_SIRET,
    )
    adresse_vendeur = _el(vendeur, NS_RAM, "PostalTradeAddress")
    _el(adresse_vendeur, NS_RAM, "CountryID", CODE_PAYS_DEFAUT)

    acheteur = _el(agreement, NS_RAM, "BuyerTradeParty")
    _el(acheteur, NS_RAM, "Name", raison_sociale_client)
    if facture.siret_destinataire:
        organisation_acheteur = _el(acheteur, NS_RAM, "SpecifiedLegalOrganization")
        _el(
            organisation_acheteur,
            NS_RAM,
            "ID",
            facture.siret_destinataire,
            schemeID=SCHEME_ID_SIRET,
        )
    if facture.reference_commande:
        commande = _el(agreement, NS_RAM, "BuyerOrderReferencedDocument")
        _el(commande, NS_RAM, "IssuerAssignedID", facture.reference_commande)

    # ram:ApplicableHeaderTradeDelivery — vide mais obligatoire au profil MINIMUM
    _el(transaction, NS_RAM, "ApplicableHeaderTradeDelivery")

    # ram:ApplicableHeaderTradeSettlement — devise et totaux
    settlement = _el(transaction, NS_RAM, "ApplicableHeaderTradeSettlement")
    _el(settlement, NS_RAM, "InvoiceCurrencyCode", facture.devise)
    totaux = _el(settlement, NS_RAM, "SpecifiedTradeSettlementHeaderMonetarySummation")
    _el(totaux, NS_RAM, "TaxBasisTotalAmount", _amount(facture.total_ht))
    _el(
        totaux,
        NS_RAM,
        "TaxTotalAmount",
        _amount(facture.total_tva),
        currencyID=facture.devise,
    )
    _el(totaux, NS_RAM, "GrandTotalAmount", _amount(facture.total_ttc))
    # Net à payer = TTC : les règlements partiels ne sont pas déduits (MVP).
    _el(totaux, NS_RAM, "DuePayableAmount", _amount(facture.total_ttc))

    xml_bytes: bytes = etree.tostring(
        root, xml_declaration=True, encoding="UTF-8", pretty_print=True
    )
    return xml_bytes
