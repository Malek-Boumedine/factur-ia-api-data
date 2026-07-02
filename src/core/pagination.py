"""
Outils communs de pagination, recherche et enveloppe de réponse.

Mutualise la mécanique partagée par les endpoints de liste (paramètres
`skip`/`limit`, comptage total, recherche insensible à la casse) afin
d'éviter la duplication dans chaque router. Les filtres et les champs de
recherche restent déclarés par chaque domaine (spécifiques au métier).
"""

from collections.abc import Sequence
from typing import Any

from fastapi import Query
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel.sql.expression import SelectOfScalar

# Nombre maximum d'éléments renvoyés en une page (garde-fou anti-abus).
MAX_LIMIT = 100


class PaginationParams:
    """
    Paramètres de pagination communs à tous les endpoints de liste.

    Injecté via `Depends(PaginationParams)` pour exposer `skip` et `limit`
    en query string avec des bornes de sécurité (`limit` plafonné à
    MAX_LIMIT pour empêcher un client de demander des milliers de lignes).
    """

    def __init__(
        self,
        skip: int = Query(0, ge=0, description="Nombre d'éléments à ignorer (offset)."),
        limit: int = Query(
            MAX_LIMIT,
            ge=1,
            le=MAX_LIMIT,
            description=f"Nombre maximum d'éléments à renvoyer (max {MAX_LIMIT}).",
        ),
    ) -> None:
        self.skip = skip
        self.limit = limit


class Page[T](BaseModel):
    """
    Enveloppe de réponse paginée.

    `total` correspond au nombre total d'éléments correspondant à la requête
    (après application des filtres et de la recherche, mais avant découpage
    en page), ce qui permet au front d'afficher « page 2/10 ».
    """

    items: list[T]
    total: int
    skip: int
    limit: int


def apply_search[T](
    statement: SelectOfScalar[T],
    columns: Sequence[Any],
    term: str | None,
) -> SelectOfScalar[T]:
    """
    Ajoute une clause de recherche insensible à la casse (`ILIKE %term%`)
    en OR sur les colonnes fournies.

    Requête paramétrée (aucune concaténation SQL) : le terme est passé comme
    valeur liée. Renvoie la requête inchangée si `term` est vide.
    """
    if not term:
        return statement
    pattern = f"%{term}%"
    return statement.where(or_(*(column.ilike(pattern) for column in columns)))


async def paginate[T](
    session: AsyncSession,
    statement: SelectOfScalar[T],
    params: PaginationParams,
) -> Page[Any]:
    """
    Exécute une requête paginée et renvoie l'enveloppe `Page`.

    Compte d'abord le total correspondant à `statement` (filtres et recherche
    déjà appliqués par l'appelant), puis récupère la tranche `skip`/`limit`.
    Le comptage réutilise la requête filtrée via une sous-requête, garantissant
    que `total` reste cohérent avec les éléments renvoyés.
    """
    count_statement = select(func.count()).select_from(statement.subquery())
    total = (await session.exec(count_statement)).one()

    paginated = statement.offset(params.skip).limit(params.limit)
    result = await session.exec(paginated)
    items = result.all()

    return Page[Any](
        items=list(items),
        total=total,
        skip=params.skip,
        limit=params.limit,
    )
