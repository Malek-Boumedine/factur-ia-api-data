"""
Endpoints du référentiel des formes juridiques.

Router mince : la logique vit dans `services.py`. Les formes juridiques sont
des données globales, communes à toutes les entreprises : aucune route n'exige
le header `x-entreprise-id`. La lecture est ouverte à tout utilisateur
authentifié (y compris pendant l'onboarding, avant tout rattachement à une
entreprise).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlmodel.ext.asyncio.session import AsyncSession

from src.auth.dependencies import get_current_user
from src.core.database import get_session
from src.entreprises.models import RefFormeJuridique
from src.formes_juridiques import services
from src.formes_juridiques.schemas import FormeJuridiqueRead
from src.utilisateurs.models import Utilisateur

router = APIRouter(prefix="/formes-juridiques", tags=["Formes juridiques"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
CurrentUserDep = Annotated[Utilisateur, Depends(get_current_user)]


@router.get("/", response_model=list[FormeJuridiqueRead])
async def list_formes(
    session: SessionDep,
    _: CurrentUserDep,
    est_actif: Annotated[
        bool | None,
        Query(description="Filtre sur le statut actif/inactif (optionnel)."),
    ] = None,
) -> list[RefFormeJuridique]:
    """
    Liste les formes juridiques de la plateforme (référentiel global), triées
    par libellé. Accessible à tout utilisateur authentifié, sans périmètre
    d'entreprise.
    """
    return await services.list_formes_juridiques(session, est_actif)
