import uuid
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import selectinload
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.clients.models import Client
from src.entreprises.models import Entreprise
from src.factures.exceptions import (
    FacturationError,
    FactureNotFoundError,
    StatutNonConfigureError,
    TauxTvaIntrouvableError,
    TransitionStatutInvalideError,
)
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


async def valider_facture_brouillon(
    session: AsyncSession,
    facture_id: int,
    id_entreprise: int,
) -> Facture:
    """
    Valide un brouillon : fige les données (snapshot) et génère le numéro définitif.
    """
    # 1. Récupérer la facture avec son statut
    statement_facture = (
        select(Facture)
        .where(Facture.id == facture_id)
        .where(Facture.id_entreprise == id_entreprise)
        .options(selectinload(Facture.statut_ref))  # type: ignore
    )
    result_facture = await session.exec(statement_facture)
    db_facture = result_facture.first()

    if db_facture is None:
        raise FactureNotFoundError(
            f"Facture ID {facture_id} introuvable pour cette entreprise."
        )

    if db_facture.statut_ref is None or db_facture.statut_ref.libelle != "Brouillon":
        statut_actuel = (
            db_facture.statut_ref.libelle if db_facture.statut_ref else "Inconnu"
        )
        raise TransitionStatutInvalideError(
            f"Impossible de valider une facture au statut '{statut_actuel}'. \
            Uniquement les brouillons."
        )

    # 2. Récupérer le statut "Validée"
    statement_statut = select(StatutFacture).where(StatutFacture.libelle == "Validée")
    result_statut = await session.exec(statement_statut)
    statut_validee = result_statut.first()

    if statut_validee is None or statut_validee.id is None:
        raise StatutNonConfigureError(
            "Le statut 'Validée' n'est pas configuré en base de données."
        )

    # 3. Génération du numéro définitif (Format: FAC-YYYYMM-XXXX)
    maintenant = datetime.now()
    prefixe_mois = f"FAC-{maintenant.strftime('%Y%m')}-"

    # Chercher la dernière facture de ce mois pour calculer la suite
    stmt_last_facture = (
        select(Facture.numero_facture)
        .where(Facture.id_entreprise == id_entreprise)
        .where(col(Facture.numero_facture).startswith(prefixe_mois))
        .order_by(col(Facture.numero_facture).desc())
    )
    result_last = await session.exec(stmt_last_facture)
    dernier_numero = result_last.first()

    if dernier_numero:
        # Extrait la fin du numéro (ex: 0005) et l'incrémente
        sequence = int(dernier_numero.split("-")[-1]) + 1
    else:
        sequence = 1

    nouveau_numero = f"{prefixe_mois}{sequence:04d}"  # Formate avec 4 zéros : 0001

    # 4. Création des Snapshots (Inaltérabilité)
    db_entreprise = await session.get(Entreprise, id_entreprise)
    db_facture.siret_emetteur = db_entreprise.siret if db_entreprise else None

    if db_facture.id_client is not None:
        db_client = await session.get(Client, db_facture.id_client)
        if db_client:
            db_facture.siret_destinataire = db_client.siret
            # On stocke les coordonnées exactes à l'instant T
            db_facture.snapshot_client = {
                "raison_sociale": db_client.raison_sociale,
                "adresse": db_client.adresse,
                "code_postal": db_client.code_postal,
                "ville": db_client.ville,
            }

    # 5. Mise à jour de la facture
    db_facture.numero_facture = nouveau_numero
    db_facture.id_statut = statut_validee.id
    db_facture.date_emission = maintenant.date()
    # La date officielle devient la date du jour

    await session.commit()

    # 6. Recharger avec les lignes pour renvoyer un objet complet à l'API
    stmt_final = (
        select(Facture)
        .where(Facture.id == db_facture.id)
        .options(selectinload(Facture.lignes))  # type: ignore
    )
    result_final = await session.exec(stmt_final)
    facture_complete = result_final.first()

    if facture_complete is None:
        raise FacturationError(
            "Erreur lors de la récupération de la facture après validation."
        )

    return facture_complete


async def generer_avoir_brouillon(
    session: AsyncSession,
    facture_id: int,
    id_entreprise: int,
    id_createur: int,
) -> Facture:
    """
    Génère un brouillon d'avoir à partir d'une facture validée existante.
    """
    # 1. Récupérer la facture d'origine avec ses lignes
    stmt_origine = (
        select(Facture)
        .where(Facture.id == facture_id)
        .where(Facture.id_entreprise == id_entreprise)
        .options(
            selectinload(Facture.statut_ref),  # type: ignore
            selectinload(Facture.lignes),  # type: ignore
        )
    )
    facture_origine = (await session.exec(stmt_origine)).first()

    if not facture_origine:
        raise FactureNotFoundError(
            "Facture d'origine introuvable pour cette entreprise."
        )

    if (
        facture_origine.statut_ref is None
        or facture_origine.statut_ref.libelle != "Validée"
    ):
        raise TransitionStatutInvalideError(
            "Seule une facture au statut 'Validée' peut faire l'objet d'un avoir."
        )

    # 2. Récupérer le statut Brouillon
    stmt_brouillon = select(StatutFacture).where(StatutFacture.libelle == "Brouillon")
    statut_brouillon = (await session.exec(stmt_brouillon)).first()

    if statut_brouillon is None or statut_brouillon.id is None:
        raise StatutNonConfigureError("Le statut 'Brouillon' n'est pas configuré.")

    # 3. Création de la coquille de l'avoir
    numero_provisoire = f"BROUILLON-AV-{uuid.uuid4().hex[:6].upper()}"

    db_avoir = Facture(
        id_entreprise=id_entreprise,
        id_createur=id_createur,
        id_client=facture_origine.id_client,
        id_document=facture_origine.id_document,
        # Lien comptable direct (FK) vers la facture d'origine
        id_facture_origine=facture_origine.id,
        numero_facture=numero_provisoire,
        date_emission=datetime.now().date(),
        date_echeance=datetime.now().date(),
        devise=facture_origine.devise,
        type_facture="avoir",
        id_statut=statut_brouillon.id,
        mode_paiement=facture_origine.mode_paiement,
        iban=facture_origine.iban,
        # Traçabilité lisible (la source de vérité reste id_facture_origine)
        reference_commande=f"Réf. Facture : {facture_origine.numero_facture}",
        notes="Avoir généré suite à une annulation ou modification.",
        # Montants stockés en négatif : un SUM global donne le vrai CA
        total_ht=-facture_origine.total_ht,
        total_tva=-facture_origine.total_tva,
        total_ttc=-facture_origine.total_ttc,
    )

    session.add(db_avoir)
    await session.flush()

    # 4. Duplication des lignes en négatif (quantités et montants inversés)
    for ligne_origine in facture_origine.lignes:
        db_ligne = FactureLigne(
            id_facture=db_avoir.id,
            ordre=ligne_origine.ordre,
            designation=ligne_origine.designation,
            quantite=-ligne_origine.quantite,
            unite=ligne_origine.unite,
            prix_unitaire_ht=ligne_origine.prix_unitaire_ht,
            id_taux_tva=ligne_origine.id_taux_tva,
            montant_ht=-ligne_origine.montant_ht,
            montant_tva=-ligne_origine.montant_tva,
            montant_ttc=-ligne_origine.montant_ttc,
        )
        session.add(db_ligne)

    await session.commit()

    # 5. Eager Loading pour le retour complet
    stmt_final = (
        select(Facture)
        .where(Facture.id == db_avoir.id)
        .options(selectinload(Facture.lignes))  # type: ignore
    )
    avoir_complet = (await session.exec(stmt_final)).first()

    if avoir_complet is None:
        raise FacturationError(
            "Erreur lors de la récupération de l'avoir après sa création."
        )

    return avoir_complet
