"""Non-régression sécurité : protection des routes d'administration plateforme.

Vérifie deux invariants structurels de tout le module ``/administration`` :

- chaque route porte le garde ``require_admin_plateforme`` ;
- aucune n'exige le header ``x-entreprise-id``.

Ces deux propriétés définissent le périmètre voulu : réservé aux administrateurs
de plateforme, et volontairement hors isolation tenant (l'administrateur agit
sur n'importe quelle entreprise, qu'il en soit membre ou non). Les vérifier
route par route plutôt qu'une fois sur le router fait échouer la suite si un
endpoint est un jour déclaré ailleurs, ou si le garde est retiré par mégarde.
"""

from fastapi import HTTPException, status
from fastapi.routing import APIRoute
from src.auth.dependencies import require_admin_plateforme
from src.main import app
from src.utilisateurs.models import Utilisateur

_PREFIXE = "/administration"


def _routes_administration() -> list[APIRoute]:
    """Routes exposées par le module d'administration de plateforme."""
    return [
        route
        for route in app.routes
        if isinstance(route, APIRoute) and route.path.startswith(_PREFIXE)
    ]


def _utilisateur(admin_plateforme: bool) -> Utilisateur:
    return Utilisateur(
        id=1,
        nom="Test",
        prenom="User",
        email="test.user@example.com",
        hash_mot_de_passe="x",  # pragma: allowlist secret
        admin_plateforme=admin_plateforme,
    )


def test_le_module_expose_bien_des_routes() -> None:
    """Garde-fou : sans routes, les assertions suivantes passeraient à vide."""
    assert _routes_administration()


def test_toutes_les_routes_exigent_un_admin_plateforme() -> None:
    """Aucune route d'administration n'est accessible sans le garde plateforme."""
    for route in _routes_administration():
        gardes = [depends.dependency for depends in route.dependencies]
        assert require_admin_plateforme in gardes, (
            f"{route.path} n'est pas protégée par require_admin_plateforme"
        )


def test_aucune_route_n_exige_le_header_tenant() -> None:
    """
    Les routes d'administration transcendent l'isolation tenant : exiger
    `x-entreprise-id` restreindrait l'administrateur aux entreprises dont il est
    membre, à l'exact opposé du besoin.
    """
    schema = app.openapi()
    for chemin, operations in schema["paths"].items():
        if not chemin.startswith(_PREFIXE):
            continue
        for methode, operation in operations.items():
            noms = {
                parametre["name"].lower()
                for parametre in operation.get("parameters", [])
            }
            assert "x-entreprise-id" not in noms, (
                f"{methode.upper()} {chemin} exige le header tenant"
            )


async def test_utilisateur_normal_refuse() -> None:
    """Un utilisateur sans le flag `admin_plateforme` est refusé (403)."""
    try:
        await require_admin_plateforme(current_user=_utilisateur(False))
    except HTTPException as exc:
        assert exc.status_code == status.HTTP_403_FORBIDDEN
    else:  # pragma: no cover - le garde doit toujours lever
        raise AssertionError("Un utilisateur normal ne doit pas passer le garde.")


async def test_admin_plateforme_autorise() -> None:
    """Un administrateur de plateforme passe et récupère son propre compte."""
    admin = _utilisateur(True)
    assert await require_admin_plateforme(current_user=admin) is admin
