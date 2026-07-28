"""Non-régression sécurité : effet réel de la suspension d'une entreprise.

Une entreprise suspendue par l'administration de plateforme doit voir tous ses
membres refusés sur les routes tenant. La vérification est portée par
``_resolve_membership``, socle commun de ``verify_tenant_access`` et de
``require_entreprise_admin`` — les deux gardes sont donc testés, y compris le
cas qui motive cette mise en commun : un administrateur d'entreprise ne doit pas
pouvoir continuer d'agir (changer de plan, par exemple) pour échapper à la
suspension.

Le test exerce le vrai code path via une session factice retournant le couple
(lien d'appartenance, entreprise) contrôlé — sans base de données, comme les
autres tests de gardes de ce dépôt.
"""

from typing import Any

import pytest
from fastapi import HTTPException, status
from src.auth.dependencies import (
    ENTREPRISE_SUSPENDUE_DETAIL,
    require_entreprise_admin,
    verify_tenant_access,
)
from src.entreprises.models import Entreprise, UtilisateurEntreprise
from src.utilisateurs.models import Utilisateur

_ENTREPRISE_ID = 42

type _Ligne = tuple[UtilisateurEntreprise, Entreprise] | None


class _Result:
    def __init__(self, ligne: _Ligne) -> None:
        self._ligne = ligne

    def first(self) -> _Ligne:
        return self._ligne


class _FakeSession:
    """Session factice retournant un couple (appartenance, entreprise)."""

    def __init__(self, ligne: _Ligne) -> None:
        self._ligne = ligne

    async def exec(self, statement: Any) -> _Result:
        return _Result(self._ligne)


def _utilisateur() -> Utilisateur:
    return Utilisateur(
        id=1,
        nom="Test",
        prenom="User",
        email="membre@example.com",
        hash_mot_de_passe="x",  # pragma: allowlist secret
    )


def _entreprise(est_actif: bool) -> Entreprise:
    return Entreprise(
        id=_ENTREPRISE_ID,
        nom_entreprise="ACME",
        est_actif=est_actif,
        motif_suspension=None if est_actif else "Impayé",
    )


def _ligne(est_admin: bool, entreprise_active: bool) -> _Ligne:
    lien = UtilisateurEntreprise(
        id_utilisateur=1, id_entreprise=_ENTREPRISE_ID, est_admin=est_admin
    )
    return lien, _entreprise(entreprise_active)


async def _acces_tenant(ligne: _Ligne) -> int:
    return await verify_tenant_access(
        x_entreprise_id=_ENTREPRISE_ID,
        current_user=_utilisateur(),
        session=_FakeSession(ligne),  # type: ignore[arg-type]
    )


async def _acces_admin_entreprise(ligne: _Ligne) -> int:
    return await require_entreprise_admin(
        x_entreprise_id=_ENTREPRISE_ID,
        current_user=_utilisateur(),
        session=_FakeSession(ligne),  # type: ignore[arg-type]
    )


async def test_membre_d_une_entreprise_active_passe() -> None:
    """Le cas nominal reste inchangé : un membre accède à son entreprise."""
    ligne = _ligne(est_admin=False, entreprise_active=True)
    assert await _acces_tenant(ligne) == _ENTREPRISE_ID


async def test_membre_d_une_entreprise_suspendue_est_refuse() -> None:
    """Une entreprise suspendue coupe l'accès de ses membres (403)."""
    ligne = _ligne(est_admin=False, entreprise_active=False)
    with pytest.raises(HTTPException) as exc:
        await _acces_tenant(ligne)
    assert exc.value.status_code == status.HTTP_403_FORBIDDEN
    assert exc.value.detail == ENTREPRISE_SUSPENDUE_DETAIL


async def test_non_membre_reste_refuse_avec_son_propre_message() -> None:
    """
    Le refus d'appartenance conserve son message d'origine : il ne doit pas
    laisser croire à une suspension, ni révéler l'état d'une entreprise dont
    l'utilisateur n'est pas membre.
    """
    with pytest.raises(HTTPException) as exc:
        await _acces_tenant(None)
    assert exc.value.status_code == status.HTTP_403_FORBIDDEN
    assert exc.value.detail != ENTREPRISE_SUSPENDUE_DETAIL


async def test_admin_entreprise_active_passe() -> None:
    """Le cas nominal du garde admin d'entreprise reste inchangé."""
    ligne = _ligne(est_admin=True, entreprise_active=True)
    assert await _acces_admin_entreprise(ligne) == _ENTREPRISE_ID


async def test_admin_entreprise_ne_peut_pas_contourner_la_suspension() -> None:
    """
    Un administrateur d'entreprise est refusé lui aussi lorsqu'elle est
    suspendue : sans cela, il pourrait changer de plan ou prolonger son
    abonnement pour se soustraire à la décision de la plateforme.
    """
    ligne = _ligne(est_admin=True, entreprise_active=False)
    with pytest.raises(HTTPException) as exc:
        await _acces_admin_entreprise(ligne)
    assert exc.value.status_code == status.HTTP_403_FORBIDDEN
    assert exc.value.detail == ENTREPRISE_SUSPENDUE_DETAIL


async def test_membre_non_admin_reste_refuse_sur_le_garde_admin() -> None:
    """Un membre non-admin d'une entreprise active est refusé pour son rôle."""
    ligne = _ligne(est_admin=False, entreprise_active=True)
    with pytest.raises(HTTPException) as exc:
        await _acces_admin_entreprise(ligne)
    assert exc.value.status_code == status.HTTP_403_FORBIDDEN
    assert exc.value.detail != ENTREPRISE_SUSPENDUE_DETAIL
