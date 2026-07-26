import uuid
from collections.abc import Sequence
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import update
from sqlalchemy.orm import selectinload
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.clients.models import Client
from src.documents.models import ExtractionOcr
from src.entreprises.models import Entreprise
from src.factures.exceptions import (
    FacturationError,
    FactureIncompleteError,
    FactureNotFoundError,
    StatutNonConfigureError,
    TauxTvaIntrouvableError,
    TransitionStatutInvalideError,
    TypeFactureNonModifiableError,
)
from src.factures.models import Facture, FactureLigne, StatutFacture, TauxTva
from src.factures.schemas import FactureCreate, FactureLigneCreate, FactureUpdate


async def _apply_lignes(
    session: AsyncSession,
    db_facture: Facture,
    lignes_in: Sequence[FactureLigneCreate],
) -> None:
    """
    Crée les lignes de la facture et calcule ses totaux HT/TVA/TTC.

    Logique de calcul partagée entre la création d'un brouillon et son
    édition (remplacement complet des lignes). La facture doit déjà être
    flushée (id disponible) et ses anciennes lignes supprimées le cas échéant.
    """
    # charger tous les taux de TVA d'un coup
    taux_ids = {ligne.id_taux_tva for ligne in lignes_in}
    statement_taux = select(TauxTva).where(TauxTva.id.in_(taux_ids))  # type: ignore
    result_taux = await session.exec(statement_taux)
    taux_map = {taux.id: taux for taux in result_taux.all()}

    total_ht_global = Decimal("0.00")
    total_tva_global = Decimal("0.00")
    centime = Decimal("0.01")

    for index, ligne_in in enumerate(lignes_in):
        taux_db = taux_map.get(ligne_in.id_taux_tva)
        if not taux_db:
            raise TauxTvaIntrouvableError(
                f"Taux de TVA introuvable pour ID: {ligne_in.id_taux_tva}."
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

    # 2. création de la coquille
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
        siret_emetteur=facture_in.siret_emetteur,
        siret_destinataire=facture_in.siret_destinataire,
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

    # 3. traitement des lignes et calcul des totaux
    await _apply_lignes(session, db_facture, facture_in.lignes)

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


async def update_facture_brouillon(
    session: AsyncSession,
    facture_id: int,
    facture_in: FactureUpdate,
    id_entreprise: int,
) -> Facture:
    """
    Met à jour un brouillon de facture : champs d'en-tête et, si fournies,
    remplacement complet des lignes avec recalcul des totaux.

    Seuls les brouillons sont modifiables : une facture validée est
    immuable (inaltérabilité légale).
    """
    # 1. Récupérer la facture avec son statut et ses lignes (isolation tenant)
    statement_facture = (
        select(Facture)
        .where(Facture.id == facture_id)
        .where(Facture.id_entreprise == id_entreprise)
        .options(
            selectinload(Facture.statut_ref),  # type: ignore
            selectinload(Facture.lignes),  # type: ignore
        )
    )
    result_facture = await session.exec(statement_facture)
    db_facture = result_facture.first()

    if db_facture is None:
        raise FactureNotFoundError("Facture introuvable dans cet espace entreprise")

    if db_facture.statut_ref is None or db_facture.statut_ref.libelle != "Brouillon":
        statut_actuel = (
            db_facture.statut_ref.libelle if db_facture.statut_ref else "Inconnu"
        )
        raise TransitionStatutInvalideError(
            f"Impossible de modifier une facture au statut '{statut_actuel}'. \
            Seuls les brouillons sont modifiables."
        )

    # 2. Mise à jour de l'en-tête (seuls les champs envoyés sont modifiés)
    donnees = facture_in.model_dump(exclude_unset=True, exclude={"lignes"})

    # Cohérence comptable : un avoir lié à une facture d'origine
    # ne peut pas changer de type.
    if (
        "type_facture" in donnees
        and donnees["type_facture"] != db_facture.type_facture
        and db_facture.id_facture_origine is not None
    ):
        raise TypeFactureNonModifiableError(
            "Impossible de changer le type d'un avoir lié à une facture d'origine."
        )

    for champ, valeur in donnees.items():
        setattr(db_facture, champ, valeur)

    # 3. Remplacement complet des lignes si le payload en fournit
    if facture_in.lignes is not None:
        for ancienne_ligne in list(db_facture.lignes):
            await session.delete(ancienne_ligne)
        await session.flush()
        await _apply_lignes(session, db_facture, facture_in.lignes)

    await session.commit()

    # 4. Recharger avec les lignes pour renvoyer un objet complet à l'API
    stmt_final = (
        select(Facture)
        .where(Facture.id == db_facture.id)
        .options(selectinload(Facture.lignes))  # type: ignore
    )
    result_final = await session.exec(stmt_final)
    facture_complete = result_final.first()

    if facture_complete is None:
        raise FacturationError(
            "Erreur lors de la récupération de la facture après modification."
        )

    return facture_complete


async def delete_facture_brouillon(
    session: AsyncSession,
    facture_id: int,
    id_entreprise: int,
) -> None:
    """
    Supprime un brouillon de facture et ses lignes.

    Seuls les brouillons sont supprimables : une facture validée est
    immuable (inaltérabilité légale) et ne peut jamais être supprimée.
    Le document source et son extraction OCR sont conservés (trace) ;
    l'extraction est simplement détachée de la facture supprimée
    (sa FK ``id_facture``, nullable, est remise à NULL).
    """
    # 1. Récupérer la facture avec son statut et ses lignes (isolation tenant)
    statement_facture = (
        select(Facture)
        .where(Facture.id == facture_id)
        .where(Facture.id_entreprise == id_entreprise)
        .options(
            selectinload(Facture.statut_ref),  # type: ignore
            selectinload(Facture.lignes),  # type: ignore
        )
    )
    result_facture = await session.exec(statement_facture)
    db_facture = result_facture.first()

    if db_facture is None:
        raise FactureNotFoundError("Facture introuvable dans cet espace entreprise")

    if db_facture.statut_ref is None or db_facture.statut_ref.libelle != "Brouillon":
        statut_actuel = (
            db_facture.statut_ref.libelle if db_facture.statut_ref else "Inconnu"
        )
        raise TransitionStatutInvalideError(
            f"Impossible de supprimer une facture au statut '{statut_actuel}'. \
            Seuls les brouillons sont supprimables."
        )

    # 2. Détacher les extractions OCR liées : l'extraction est conservée
    # (trace de ce que l'OCR a lu), seule sa référence facture est effacée.
    # Sans ce détachement, la FK extraction_ocr.id_facture bloque le DELETE.
    detach_statement = (
        update(ExtractionOcr)
        .where(col(ExtractionOcr.id_facture) == facture_id)
        .values(id_facture=None)
    )
    await session.execute(detach_statement)

    # 3. Supprimer les lignes explicitement (pas de cascade configurée)
    for ligne in list(db_facture.lignes):
        await session.delete(ligne)

    # 4. Pousser le détachement et les suppressions de lignes en base
    # avant le DELETE de la facture (ordre garanti côté MySQL).
    await session.flush()

    # 5. Supprimer la facture ; le commit scelle la transaction unique.
    await session.delete(db_facture)
    await session.commit()


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

    # Complétude : une facture légale doit avoir un destinataire
    # (le snapshot client serait vide sinon).
    if db_facture.id_client is None:
        raise FactureIncompleteError(
            "Impossible de valider : aucun client n'est associé à ce brouillon."
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
    if db_facture.id_facture_origine is not None:
        # Avoir : on refige depuis la facture d'origine, pas depuis les
        # référentiels courants — l'avoir doit refléter la facture annulée
        # telle qu'elle a été émise, même si la fiche client a changé depuis.
        facture_origine = await session.get(Facture, db_facture.id_facture_origine)
        if facture_origine is not None:
            db_facture.siret_emetteur = facture_origine.siret_emetteur
            db_facture.siret_destinataire = facture_origine.siret_destinataire
            db_facture.snapshot_client = (
                dict(facture_origine.snapshot_client)
                if facture_origine.snapshot_client is not None
                else None
            )
    else:
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
        # L'avoir fige l'état de la facture annulée : on recopie les snapshots
        # de l'origine (copie du dict JSON, pas de référence partagée)
        siret_emetteur=facture_origine.siret_emetteur,
        siret_destinataire=facture_origine.siret_destinataire,
        snapshot_client=dict(facture_origine.snapshot_client)
        if facture_origine.snapshot_client is not None
        else None,
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
