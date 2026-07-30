"""Orchestration de la génération d'un fichier Factur-X.

Assemble le PDF visuel (reportlab) et le XML CII MINIMUM (lxml), puis délègue
à la librairie ``factur-x`` (Akretion) l'embedding du XML et la conversion en
PDF/A-3 (métadonnées XMP, relation AF). Le XML est validé contre le XSD
officiel embarqué dans la librairie — aucun appel réseau.
"""

from facturx import generate_from_binary
from src.entreprises.models import Entreprise
from src.factures.models import Facture
from src.facturx.cii import build_cii_minimum_xml
from src.facturx.pdf import build_invoice_pdf

# Nom de fichier proposé au téléchargement (le XML embarqué s'appelle
# toujours factur-x.xml, imposé par la spécification).
SUFFIXE_FICHIER = "-facturx.pdf"


def facturx_filename(facture: Facture) -> str:
    """Nom du fichier proposé au téléchargement."""
    return f"{facture.numero_facture}{SUFFIXE_FICHIER}"


def generate_facturx(facture: Facture, entreprise: Entreprise) -> bytes:
    """Génère le fichier Factur-X (PDF/A-3 + XML CII) d'une facture validée.

    Lève ``DonneesFacturXManquantesError`` si une donnée obligatoire du XML
    est absente (SIRET émetteur, snapshot client).
    """
    xml_bytes = build_cii_minimum_xml(facture, entreprise)
    pdf_bytes = build_invoice_pdf(facture, entreprise)

    pdf_metadata = {
        "author": entreprise.nom_entreprise,
        "keywords": "Factur-X, facture",
        "title": f"Facture {facture.numero_facture}",
        "subject": (
            f"Facture {facture.numero_facture} émise par {entreprise.nom_entreprise}"
        ),
    }
    facturx_pdf: bytes = generate_from_binary(
        pdf_bytes,
        xml_bytes,
        flavor="factur-x",
        level="minimum",
        check_xsd=True,
        pdf_metadata=pdf_metadata,
    )
    return facturx_pdf
