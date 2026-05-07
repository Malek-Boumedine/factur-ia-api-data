import uuid
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import selectinload
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.factures.exceptions import StatutNonConfigureError, TauxTvaIntrouvableError
from src.factures.models import Facture, FactureLigne, StatutFacture, TauxTva
from src.factures.schemas import FactureCreate


async def create_facture_brouillon(
    session: AsyncSession,
    facture_in: FactureCreate,
    id_entreprise: int,
    id_createur: int,
) -> Facture:
    # 1. Statut
    statement_statut = select(StatutFacture).where(StatutFacture.libelle == "Brouillon")
    result_statut = await session.exec(statement_statut)
    statut_brouillon = result_statut.first()

    if not statut_brouillon:
        raise StatutNonConfigureError(
            "Erreur système : Le statut 'Brouillon' n'est pas configuré."
        )

    numero_provisoire = f"BROUILLON-{uuid.uuid4().hex[:8].upper()}"

    # 2. charger tous les taux de TVA d'un coup
    taux_ids = {ligne.id_taux_tva for ligne in facture_in.lignes}
    statement_taux = select(TauxTva).where(TauxTva.id.in_(taux_ids))  # type: ignore
    result_taux = await session.exec(statement_taux)
    taux_map = {t.id: t for t in result_taux.all()}

    # 3. création de la coquille
    db_facture = Facture(
        id_entreprise=id_entreprise,
        id_createur=id_createur,
        id_client=facture_in.id_client,
        id_document=facture_in.id_document,
        numero_facture=numero_provisoire,
        date_emission=facture_in.date_emission,
        date_echeance=facture_in.date_echeance,
        devise=facture_in.devise,
        type_facture=facture_in.type_facture,
        id_statut=statut_brouillon.id,
        mode_paiement=facture_in.mode_paiement,
        iban=facture_in.iban,
        reference_commande=facture_in.reference_commande,
        notes=facture_in.notes,
        total_ht=Decimal("0.00"),
        total_tva=Decimal("0.00"),
        total_ttc=Decimal("0.00"),
    )

    session.add(db_facture)
    await session.flush()

    # 4. traitement des lignes
    total_ht_global = Decimal("0.00")
    total_tva_global = Decimal("0.00")
    centime = Decimal("0.01")

    for index, ligne_in in enumerate(facture_in.lignes):
        # Récupération depuis le dictionnaireen mémoire
        taux_db = taux_map.get(ligne_in.id_taux_tva)
        if not taux_db:
            raise TauxTvaIntrouvableError(
                f"Taux de TVA introuvable \
                    pour ID: {ligne_in.id_taux_tva}."
            )

        montant_ht = (ligne_in.quantite * ligne_in.prix_unitaire_ht).quantize(
            centime, rounding=ROUND_HALF_UP
        )
        montant_tva = (montant_ht * (taux_db.taux / Decimal("100"))).quantize(
            centime, rounding=ROUND_HALF_UP
        )
        montant_ttc = montant_ht + montant_tva

        # CORRECTION ORDRE : index est utilisé
        # par défaut si ordre n'est pas précisé
        ordre_final = ligne_in.ordre if ligne_in.ordre is not None else index

        db_ligne = FactureLigne(
            id_facture=db_facture.id,
            ordre=ordre_final,
            designation=ligne_in.designation,
            quantite=ligne_in.quantite,
            unite=ligne_in.unite,
            prix_unitaire_ht=ligne_in.prix_unitaire_ht,
            id_taux_tva=taux_db.id,
            montant_ht=montant_ht,
            montant_tva=montant_tva,
            montant_ttc=montant_ttc,
        )
        session.add(db_ligne)

        total_ht_global += montant_ht
        total_tva_global += montant_tva

    db_facture.total_ht = total_ht_global.quantize(centime, rounding=ROUND_HALF_UP)
    db_facture.total_tva = total_tva_global.quantize(centime, rounding=ROUND_HALF_UP)
    db_facture.total_ttc = (total_ht_global + total_tva_global).quantize(
        centime, rounding=ROUND_HALF_UP
    )

    await session.commit()

    statement = (
        select(Facture)
        .where(Facture.id == db_facture.id)
        .options(selectinload(Facture.lignes))  # type: ignore
    )
    result = await session.exec(statement)
    facture_complete = result.first()

    if facture_complete is None:
        raise StatutNonConfigureError(
            "Erreur critique : La facture créée est introuvable après commit."
        )

    return facture_complete
