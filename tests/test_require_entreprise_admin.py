"""Non-régression sécurité : garde-fou ``require_entreprise_admin``.

Vérifie que la dépendance n'autorise que les administrateurs de l'entreprise
active : non-membre -> 403, membre non-admin -> 403, admin -> laisse passer et
retourne l'``id`` de l'entreprise du header.

Le test exerce le vrai code path via une session factice retournant le couple
(lien ``UtilisateurEntreprise``, ``Entreprise``) que résout la requête du garde
— sans base de données (pas d'infra DB de test avant l'Epic 6).

Le volet « entreprise suspendue » du même garde est couvert par
``test_entreprise_suspendue.py``.
"""

from typing import Any

import pytest
from fastapi import HTTPException, status
from src.auth.dependencies import require_entreprise_admin
from src.entreprises.models import Entreprise, UtilisateurEntreprise
from src.utilisateurs.models import Utilisateur

type _Ligne = tuple[UtilisateurEntreprise, Entreprise] | None


class _Result:
    def __init__(self, ligne: _Ligne) -> None:
        self._ligne = ligne

    def first(self) -> _Ligne:
        return self._ligne


class _FakeSession:
    """Session factice retournant un couple appartenance/entreprise prédéfini."""

    def __init__(self, ligne: _Ligne) -> None:
        self._ligne = ligne

    async def exec(self, statement: Any) -> _Result:
        return _Result(self._ligne)


def _user() -> Utilisateur:
    return Utilisateur(
        id=1,
        nom="Test",
        prenom="User",
        email="admin@example.com",
        hash_mot_de_passe="x",  # pragma: allowlist secret
    )


def _ligne(est_admin: bool) -> _Ligne:
    """Couple appartenance/entreprise, l'entreprise étant active."""
    lien = UtilisateurEntreprise(
        id_utilisateur=1, id_entreprise=42, est_admin=est_admin
    )
    return lien, Entreprise(id=42, nom_entreprise="ACME", est_actif=True)


async def _call(ligne: _Ligne) -> int:
    return await require_entreprise_admin(
        x_entreprise_id=42,
        current_user=_user(),
        session=_FakeSession(ligne),  # type: ignore[arg-type]
    )


async def test_non_membre_est_refuse() -> None:
    """Un utilisateur non rattaché à l'entreprise du header est refusé (403)."""
    with pytest.raises(HTTPException) as exc:
        await _call(ligne=None)
    assert exc.value.status_code == status.HTTP_403_FORBIDDEN


async def test_membre_non_admin_est_refuse() -> None:
    """Un membre sans droit d'administration est refusé (403)."""
    with pytest.raises(HTTPException) as exc:
        await _call(ligne=_ligne(est_admin=False))
    assert exc.value.status_code == status.HTTP_403_FORBIDDEN


async def test_admin_entreprise_est_autorise() -> None:
    """Un administrateur de l'entreprise active passe et récupère son id."""
    assert await _call(ligne=_ligne(est_admin=True)) == 42
