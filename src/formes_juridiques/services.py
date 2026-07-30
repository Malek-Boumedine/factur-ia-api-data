"""
Logique métier du référentiel des formes juridiques.

Les formes juridiques sont des données de référence globales (aucun périmètre
entreprise). Lecture seule : le référentiel est alimenté par le seed
(`src/core/seed.py`).
"""

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.entreprises.models import RefFormeJuridique


async def list_formes_juridiques(
    session: AsyncSession, est_actif: bool | None = None
) -> list[RefFormeJuridique]:
    """
    Liste les formes juridiques triées par libellé, avec filtre optionnel sur
    le statut actif. Le front utilise `est_actif=true` pour remplir ses
    listes déroulantes.
    """
    statement = select(RefFormeJuridique)
    if est_actif is not None:
        statement = statement.where(RefFormeJuridique.est_actif == est_actif)
    statement = statement.order_by(col(RefFormeJuridique.libelle))

    result = await session.exec(statement)
    return list(result.all())
