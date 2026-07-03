"""Non-régression sécurité : isolation RBAC par entreprise (tenant).

Vérifie que ``RequirePermission`` scope la vérification de permission à
l'entreprise active (``x-entreprise-id``, validée par ``verify_tenant_access``).
Ferme la faille d'escalade de privilèges inter-tenant : un rôle élevé détenu
dans l'entreprise A ne doit conférer aucun droit quand l'utilisateur agit sur
l'entreprise B.

Le test exerce le vrai code path de ``RequirePermission.__call__`` via une
session factice qui capture le ``statement`` SQL construit — sans base de
données — puis inspecte la requête compilée. Il n'existe pas encore d'infra de
test à base de DB (Epic 6) ; cette approche teste précisément la clause de
scope sans dépendance supplémentaire.
"""

from typing import Any

import pytest
from fastapi import HTTPException
from src.auth.dependencies import RequirePermission
from src.utilisateurs.models import Utilisateur


class _CapturingResult:
    """Résultat factice : aucune permission trouvée (force le 403)."""

    def first(self) -> None:
        return None


class _CapturingSession:
    """Session factice capturant le statement passé à ``exec`` (pas de DB)."""

    def __init__(self) -> None:
        self.statement: Any = None

    async def exec(self, statement: Any) -> _CapturingResult:
        self.statement = statement
        return _CapturingResult()


def _make_user() -> Utilisateur:
    return Utilisateur(
        id=1,
        nom="Test",
        prenom="User",
        email="test.user@example.com",
        hash_mot_de_passe="x",  # pragma: allowlist secret
    )


async def _capture_statement(active_entreprise: int) -> str:
    """Exécute RequirePermission et retourne le SQL compilé (literal binds)."""
    session = _CapturingSession()
    dependency = RequirePermission("client:delete")

    # Aucune permission n'est retournée par la session factice : l'appel lève
    # un 403, mais le statement a déjà été capturé lors de `exec`.
    with pytest.raises(HTTPException):
        await dependency(
            current_user=_make_user(),
            entreprise_id=active_entreprise,
            session=session,  # type: ignore[arg-type]
        )

    assert session.statement is not None
    compiled = session.statement.compile(compile_kwargs={"literal_binds": True})
    return str(compiled)


async def test_permission_scopee_a_l_entreprise_active() -> None:
    """La requête filtre bien sur l'entreprise active transmise dans le header."""
    sql = await _capture_statement(active_entreprise=42)

    # Le scope par tenant est présent...
    assert "utilisateur_role.id_entreprise" in sql
    # ...et pointe sur l'entreprise active (pas une autre).
    assert "42" in sql


async def test_roles_globaux_honores() -> None:
    """Les rôles globaux (id_entreprise NULL) restent pris en compte (variante B)."""
    sql = await _capture_statement(active_entreprise=42)

    assert "IS NULL" in sql.upper()


async def test_scope_suit_l_entreprise_transmise() -> None:
    """Changer l'entreprise active change la valeur filtrée (pas de fuite)."""
    sql_a = await _capture_statement(active_entreprise=7)
    sql_b = await _capture_statement(active_entreprise=99)

    assert "7" in sql_a
    assert "99" in sql_b
