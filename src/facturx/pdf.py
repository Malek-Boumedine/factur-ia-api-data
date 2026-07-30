"""Génération du PDF visuel de la facture (reportlab).

Ce PDF est la représentation lisible de la facture : il porte tout ce que le
profil Factur-X MINIMUM ne met pas dans le XML (lignes, IBAN, échéance,
mentions). Il sert de base à l'embedding du XML CII pour produire le PDF/A-3.

Les relations ``facture.lignes`` et ``ligne.taux_tva_ref`` doivent avoir été
chargées en eager par l'appelant (contexte async).
"""

from decimal import Decimal
from io import BytesIO
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from src.entreprises.models import Entreprise
from src.factures.models import Facture, FactureLigne, TypeFacture


def _fmt_montant(value: Decimal, devise: str) -> str:
    return f"{value.quantize(Decimal('0.01'))} {devise}"


def _ligne_taux_tva(ligne: FactureLigne) -> str:
    taux = ligne.taux_tva_ref
    if taux is None:
        return ""
    return f"{taux.taux.quantize(Decimal('0.01'))} %"


def _bloc_parties(facture: Facture, entreprise: Entreprise, styles: Any) -> Table:
    """Blocs émetteur / destinataire côte à côte."""
    emetteur_lignes = [f"<b>{entreprise.nom_entreprise}</b>"]
    if facture.siret_emetteur:
        emetteur_lignes.append(f"SIRET : {facture.siret_emetteur}")

    snapshot = facture.snapshot_client or {}
    destinataire_lignes = [f"<b>{snapshot.get('raison_sociale', '')}</b>"]
    if snapshot.get("adresse"):
        destinataire_lignes.append(str(snapshot["adresse"]))
    ville = " ".join(
        str(snapshot[cle]) for cle in ("code_postal", "ville") if snapshot.get(cle)
    )
    if ville:
        destinataire_lignes.append(ville)
    if facture.siret_destinataire:
        destinataire_lignes.append(f"SIRET : {facture.siret_destinataire}")

    tableau = Table(
        [
            [
                Paragraph("Émetteur", styles["Heading4"]),
                Paragraph("Destinataire", styles["Heading4"]),
            ],
            [
                Paragraph("<br/>".join(emetteur_lignes), styles["Normal"]),
                Paragraph("<br/>".join(destinataire_lignes), styles["Normal"]),
            ],
        ],
        colWidths=[85 * mm, 85 * mm],
    )
    tableau.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return tableau


def _tableau_lignes(facture: Facture, styles: Any) -> Table:
    entetes = ["Désignation", "Qté", "Unité", "PU HT", "TVA", "Montant HT"]
    donnees: list[list[Any]] = [entetes]
    for ligne in facture.lignes:
        donnees.append(
            [
                Paragraph(ligne.designation, styles["Normal"]),
                str(ligne.quantite),
                ligne.unite or "",
                _fmt_montant(ligne.prix_unitaire_ht, facture.devise),
                _ligne_taux_tva(ligne),
                _fmt_montant(ligne.montant_ht, facture.devise),
            ]
        )
    tableau = Table(
        donnees, colWidths=[60 * mm, 15 * mm, 18 * mm, 27 * mm, 18 * mm, 32 * mm]
    )
    tableau.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8E8E8")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
            ]
        )
    )
    return tableau


def _tableau_totaux(facture: Facture) -> Table:
    tableau = Table(
        [
            ["Total HT", _fmt_montant(facture.total_ht, facture.devise)],
            ["Total TVA", _fmt_montant(facture.total_tva, facture.devise)],
            ["Total TTC", _fmt_montant(facture.total_ttc, facture.devise)],
        ],
        colWidths=[40 * mm, 40 * mm],
        hAlign="RIGHT",
    )
    tableau.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
            ]
        )
    )
    return tableau


def build_invoice_pdf(facture: Facture, entreprise: Entreprise) -> bytes:
    """Génère le PDF de la facture et le renvoie en mémoire (bytes)."""
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        title=f"Facture {facture.numero_facture}",
        author=entreprise.nom_entreprise,
    )
    styles = getSampleStyleSheet()
    style_petit = ParagraphStyle("Petit", parent=styles["Normal"], fontSize=8)

    titre = "AVOIR" if facture.type_facture == TypeFacture.AVOIR else "FACTURE"
    elements: list[Any] = [
        Paragraph(f"{titre} {facture.numero_facture}", styles["Title"]),
        Spacer(1, 4 * mm),
        _bloc_parties(facture, entreprise, styles),
        Spacer(1, 4 * mm),
    ]

    infos = [f"Date d'émission : {facture.date_emission.strftime('%d/%m/%Y')}"]
    if facture.date_echeance:
        infos.append(f"Date d'échéance : {facture.date_echeance.strftime('%d/%m/%Y')}")
    if facture.reference_commande:
        infos.append(f"Référence commande : {facture.reference_commande}")
    elements.append(Paragraph("<br/>".join(infos), styles["Normal"]))
    elements.append(Spacer(1, 6 * mm))

    elements.append(_tableau_lignes(facture, styles))
    elements.append(Spacer(1, 6 * mm))
    elements.append(_tableau_totaux(facture))
    elements.append(Spacer(1, 6 * mm))

    paiement = []
    if facture.mode_paiement:
        paiement.append(f"Mode de paiement : {facture.mode_paiement}")
    if facture.iban:
        paiement.append(f"IBAN : {facture.iban}")
    if paiement:
        elements.append(Paragraph("<br/>".join(paiement), styles["Normal"]))
        elements.append(Spacer(1, 4 * mm))

    if facture.notes:
        elements.append(Paragraph(facture.notes, style_petit))

    document.build(elements)
    return buffer.getvalue()
