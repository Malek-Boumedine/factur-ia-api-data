"""
Logique métier du référentiel des taux de TVA.

Les taux sont des données de référence globales (aucun périmètre entreprise).
La suppression est toujours un soft delete (`est_actif=False`) : des lignes de
facture validées — légalement inaltérables — et des produits du catalogue
référencent `id_taux_tva`, une suppression physique est donc proscrite.
"""

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.factures.models import TauxTva
from src.taux_tva.schemas import TauxTvaCreate, TauxTvaUpdate


async def list_taux_tva(
    session: AsyncSession, est_actif: bool | None = None
) -> list[TauxTva]:
    """
    Liste les taux de TVA, avec filtre optionnel sur le statut actif.
    Le front utilise `est_actif=true` pour remplir ses listes déroulantes.
    """
    statement = select(TauxTva)
    if est_actif is not None:
        statement = statement.where(TauxTva.est_actif == est_actif)
    statement = statement.order_by(col(TauxTva.taux))

    result = await session.exec(statement)
    return list(result.all())


async def get_taux_tva(session: AsyncSession, taux_tva_id: int) -> TauxTva:
    """Charge un taux de TVA par son ID ou lève une 404."""
    taux = await session.get(TauxTva, taux_tva_id)
    if taux is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Taux de TVA introuvable.",
        )
    return taux


async def create_taux_tva(session: AsyncSession, taux_in: TauxTvaCreate) -> TauxTva:
    """
    Crée un nouveau taux de TVA.
    Le champ `taux` est unique en base : un doublon renvoie une 409.
    """
    db_taux = TauxTva.model_validate(taux_in)
    session.add(db_taux)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Un taux de TVA à {taux_in.taux} % existe déjà.",
        ) from None

    await session.refresh(db_taux)
    return db_taux


async def update_taux_tva(
    session: AsyncSession, taux_tva_id: int, taux_in: TauxTvaUpdate
) -> TauxTva:
    """
    Met à jour partiellement un taux de TVA (dont la réactivation via
    `est_actif=true`). Un conflit d'unicité sur `taux` renvoie une 409.
    """
    db_taux = await get_taux_tva(session, taux_tva_id)

    update_data = taux_in.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_taux, key, value)

    session.add(db_taux)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Un taux de TVA à {taux_in.taux} % existe déjà.",
        ) from None

    await session.refresh(db_taux)
    return db_taux


async def deactivate_taux_tva(session: AsyncSession, taux_tva_id: int) -> None:
    """
    Désactive un taux de TVA (soft delete, idempotent).

    Jamais de suppression physique : les factures et produits existants
    doivent pouvoir continuer à référencer ce taux. La réactivation passe
    par un PATCH avec `est_actif=true`.
    """
    db_taux = await get_taux_tva(session, taux_tva_id)

    if db_taux.est_actif:
        db_taux.est_actif = False
        session.add(db_taux)
        await session.commit()
