"""Non-régression sécurité : garde-fou ``require_entreprise_admin``.

Vérifie que la dépendance n'autorise que les administrateurs de l'entreprise
active : non-membre -> 403, membre non-admin -> 403, admin -> laisse passer et
retourne l'``id`` de l'entreprise du header.

Le test exerce le vrai code path via une session factice retournant un lien
``UtilisateurEntreprise`` contrôlé — sans base de données (pas d'infra DB de
test avant l'Epic 6).
"""

from typing import Any

import pytest
from fastapi import HTTPException, status
from src.auth.dependencies import require_entreprise_admin
from src.entreprises.models import UtilisateurEntreprise
from src.utilisateurs.models import Utilisateur


class _Result:
    def __init__(self, lien: UtilisateurEntreprise | None) -> None:
        self._lien = lien

    def first(self) -> UtilisateurEntreprise | None:
        return self._lien


class _FakeSession:
    """Session factice retournant un lien d'appartenance prédéfini."""

    def __init__(self, lien: UtilisateurEntreprise | None) -> None:
        self._lien = lien

    async def exec(self, statement: Any) -> _Result:
        return _Result(self._lien)


def _user() -> Utilisateur:
    return Utilisateur(
        id=1,
        nom="Test",
        prenom="User",
        email="admin@example.com",
        hash_mot_de_passe="x",  # pragma: allowlist secret
    )


async def _call(lien: UtilisateurEntreprise | None) -> int:
    return await require_entreprise_admin(
        x_entreprise_id=42,
        current_user=_user(),
        session=_FakeSession(lien),  # type: ignore[arg-type]
    )


async def test_non_membre_est_refuse() -> None:
    """Un utilisateur non rattaché à l'entreprise du header est refusé (403)."""
    with pytest.raises(HTTPException) as exc:
        await _call(lien=None)
    assert exc.value.status_code == status.HTTP_403_FORBIDDEN


async def test_membre_non_admin_est_refuse() -> None:
    """Un membre sans droit d'administration est refusé (403)."""
    lien = UtilisateurEntreprise(id_utilisateur=1, id_entreprise=42, est_admin=False)
    with pytest.raises(HTTPException) as exc:
        await _call(lien=lien)
    assert exc.value.status_code == status.HTTP_403_FORBIDDEN


async def test_admin_entreprise_est_autorise() -> None:
    """Un administrateur de l'entreprise active passe et récupère son id."""
    lien = UtilisateurEntreprise(id_utilisateur=1, id_entreprise=42, est_admin=True)
    assert await _call(lien=lien) == 42
