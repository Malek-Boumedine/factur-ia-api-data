"""Non-régression : garde-fous de suppression de l'administration plateforme.

Couvre les décisions à enjeu de ce module :

- **auto-protection** : un administrateur ne peut ni se supprimer ni se
  désactiver lui-même, un compte protégé reste intouchable, et le dernier
  administrateur de plateforme ne peut pas disparaître ;
- **piste d'audit** : un compte auteur de données comptables ne peut pas être
  supprimé, seulement désactivé ;
- **inaltérabilité** : une entreprise porteuse d'une facture émise ne peut pas
  être supprimée, sans contournement possible ;
- **arbitrage de support** : la réactivation d'un compte par un administrateur
  de plateforme n'est jamais soumise à la limite d'utilisateurs du plan.

Les décisions sont exercées sur le vrai code path ; seules les agrégations SQL
sont remplacées (session factice et substitution des compteurs), afin de tester
l'ordre et la nature des garde-fous sans base de données.
"""

from typing import Any

import pytest
from fastapi import HTTPException, status
from src.abonnements import services as abonnements_services
from src.administration import services
from src.administration.schemas import CompteursEntreprise, CompteursUtilisateur
from src.entreprises.models import Entreprise
from src.utilisateurs.models import Utilisateur

_ADMIN_ID = 1
_CIBLE_ID = 2
_ENTREPRISE_ID = 42


class _FakeSession:
    """
    Session factice : résout `get` depuis une table en mémoire et enregistre
    les écritures, sans jamais toucher à une base.
    """

    def __init__(self, objets: dict[int, Any] | None = None) -> None:
        self._objets = objets or {}
        self.supprimes: list[Any] = []
        self.commits = 0
        self.executions = 0

    async def get(self, modele: type, identifiant: int) -> Any:
        return self._objets.get(identifiant)

    async def execute(self, statement: Any) -> None:
        self.executions += 1

    async def delete(self, objet: Any) -> None:
        self.supprimes.append(objet)

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, objet: Any) -> None:
        return None

    def add(self, objet: Any) -> None:
        return None


def _utilisateur(
    identifiant: int,
    *,
    admin_plateforme: bool = False,
    compte_protege: bool = False,
    est_actif: bool = True,
) -> Utilisateur:
    return Utilisateur(
        id=identifiant,
        nom="Cible",
        prenom="Test",
        email=f"user{identifiant}@example.com",
        hash_mot_de_passe="x",  # pragma: allowlist secret
        admin_plateforme=admin_plateforme,
        compte_protege=compte_protege,
        est_actif=est_actif,
    )


def _admin() -> Utilisateur:
    return _utilisateur(_ADMIN_ID, admin_plateforme=True)


def _preparer_utilisateur(
    monkeypatch: pytest.MonkeyPatch,
    *,
    total_admins: int = 5,
    entreprises_orphelines: list[str] | None = None,
    compteurs: CompteursUtilisateur | None = None,
) -> None:
    """Neutralise les agrégations SQL de `supprimer_utilisateur`."""

    async def _count(session: Any, statement: Any) -> int:
        return total_admins

    async def _seul_admin(session: Any, utilisateur_id: int) -> list[str]:
        return entreprises_orphelines or []

    async def _compteurs(session: Any, utilisateur_id: int) -> CompteursUtilisateur:
        return compteurs or CompteursUtilisateur()

    monkeypatch.setattr(services, "_count", _count)
    monkeypatch.setattr(services, "_entreprises_dont_il_est_seul_admin", _seul_admin)
    monkeypatch.setattr(services, "compteurs_utilisateur", _compteurs)


def _preparer_entreprise(
    monkeypatch: pytest.MonkeyPatch, compteurs: CompteursEntreprise
) -> None:
    """Neutralise les agrégations SQL de `supprimer_entreprise`."""

    async def _compteurs(session: Any, entreprise_id: int) -> CompteursEntreprise:
        return compteurs

    monkeypatch.setattr(services, "compteurs_entreprise", _compteurs)


# ---------------------------------------------------------------------------
# Suppression d'un utilisateur
# ---------------------------------------------------------------------------


async def test_compte_protege_non_supprimable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Le compte racine protégé est refusé avant tout autre contrôle."""
    _preparer_utilisateur(monkeypatch)
    cible = _utilisateur(_CIBLE_ID, compte_protege=True)
    session = _FakeSession({_CIBLE_ID: cible})

    with pytest.raises(HTTPException) as exc:
        await services.supprimer_utilisateur(session, _CIBLE_ID, _admin())  # type: ignore[arg-type]

    assert exc.value.status_code == status.HTTP_403_FORBIDDEN
    assert session.supprimes == []


async def test_auto_suppression_refusee(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un administrateur ne peut pas supprimer son propre compte."""
    _preparer_utilisateur(monkeypatch)
    admin = _admin()
    session = _FakeSession({_ADMIN_ID: admin})

    with pytest.raises(HTTPException) as exc:
        await services.supprimer_utilisateur(session, _ADMIN_ID, admin)  # type: ignore[arg-type]

    assert exc.value.status_code == status.HTTP_403_FORBIDDEN
    assert session.supprimes == []


async def test_dernier_admin_plateforme_non_supprimable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La plateforme doit toujours conserver au moins un administrateur."""
    _preparer_utilisateur(monkeypatch, total_admins=1)
    cible = _utilisateur(_CIBLE_ID, admin_plateforme=True)
    session = _FakeSession({_CIBLE_ID: cible})

    with pytest.raises(HTTPException) as exc:
        await services.supprimer_utilisateur(session, _CIBLE_ID, _admin())  # type: ignore[arg-type]

    assert exc.value.status_code == status.HTTP_409_CONFLICT
    assert session.supprimes == []


async def test_avant_dernier_admin_plateforme_supprimable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tant qu'il en reste un autre, un admin plateforme reste supprimable."""
    _preparer_utilisateur(monkeypatch, total_admins=2)
    cible = _utilisateur(_CIBLE_ID, admin_plateforme=True)
    session = _FakeSession({_CIBLE_ID: cible})

    await services.supprimer_utilisateur(session, _CIBLE_ID, _admin())  # type: ignore[arg-type]

    assert session.supprimes == [cible]
    assert session.commits == 1


async def test_seul_admin_d_une_entreprise_peuplee_non_supprimable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Supprimer le seul administrateur d'une entreprise qui compte d'autres
    membres la laisserait sans personne pour l'administrer.
    """
    _preparer_utilisateur(monkeypatch, entreprises_orphelines=["ACME"])
    session = _FakeSession({_CIBLE_ID: _utilisateur(_CIBLE_ID)})

    with pytest.raises(HTTPException) as exc:
        await services.supprimer_utilisateur(session, _CIBLE_ID, _admin())  # type: ignore[arg-type]

    assert exc.value.status_code == status.HTTP_409_CONFLICT
    assert "ACME" in exc.value.detail
    assert session.supprimes == []


async def test_auteur_de_donnees_comptables_non_supprimable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Un compte ayant émis des factures n'est pas supprimable : la piste d'audit
    doit rester nominative. Le message oriente vers la désactivation.
    """
    _preparer_utilisateur(
        monkeypatch, compteurs=CompteursUtilisateur(factures_creees=3)
    )
    session = _FakeSession({_CIBLE_ID: _utilisateur(_CIBLE_ID)})

    with pytest.raises(HTTPException) as exc:
        await services.supprimer_utilisateur(session, _CIBLE_ID, _admin())  # type: ignore[arg-type]

    assert exc.value.status_code == status.HTTP_409_CONFLICT
    assert "ésactivez" in exc.value.detail
    assert session.supprimes == []


async def test_compte_vierge_supprimable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un compte sans donnée ni responsabilité franchit les cinq garde-fous."""
    _preparer_utilisateur(monkeypatch)
    cible = _utilisateur(_CIBLE_ID)
    session = _FakeSession({_CIBLE_ID: cible})

    await services.supprimer_utilisateur(session, _CIBLE_ID, _admin())  # type: ignore[arg-type]

    assert session.supprimes == [cible]
    assert session.commits == 1


async def test_utilisateur_introuvable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un identifiant inconnu renvoie 404, jamais une erreur serveur."""
    _preparer_utilisateur(monkeypatch)
    session = _FakeSession({})

    with pytest.raises(HTTPException) as exc:
        await services.supprimer_utilisateur(session, 999, _admin())  # type: ignore[arg-type]

    assert exc.value.status_code == status.HTTP_404_NOT_FOUND


# ---------------------------------------------------------------------------
# Activation / désactivation d'un utilisateur
# ---------------------------------------------------------------------------


async def test_auto_desactivation_refusee() -> None:
    """Un administrateur ne peut pas se désactiver lui-même."""
    admin = _admin()
    session = _FakeSession({_ADMIN_ID: admin})

    with pytest.raises(HTTPException) as exc:
        await services.definir_activite_utilisateur(session, _ADMIN_ID, False, admin)  # type: ignore[arg-type]

    assert exc.value.status_code == status.HTTP_403_FORBIDDEN
    assert admin.est_actif is True


async def test_compte_protege_non_desactivable() -> None:
    """Le compte racine protégé ne peut pas être désactivé."""
    cible = _utilisateur(_CIBLE_ID, compte_protege=True)
    session = _FakeSession({_CIBLE_ID: cible})

    with pytest.raises(HTTPException) as exc:
        await services.definir_activite_utilisateur(
            session,  # type: ignore[arg-type]
            _CIBLE_ID,
            False,
            _admin(),
        )

    assert exc.value.status_code == status.HTTP_403_FORBIDDEN
    assert cible.est_actif is True


async def test_desactivation_d_un_autre_compte() -> None:
    """La désactivation d'un tiers est le cas nominal et persiste l'état."""
    cible = _utilisateur(_CIBLE_ID)
    session = _FakeSession({_CIBLE_ID: cible})

    resultat = await services.definir_activite_utilisateur(
        session,  # type: ignore[arg-type]
        _CIBLE_ID,
        False,
        _admin(),
    )

    assert resultat.est_actif is False
    assert session.commits == 1


async def test_reactivation_ignore_la_limite_du_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    L'administrateur de plateforme agit en support : la limite d'utilisateurs du
    plan ne doit jamais bloquer une réactivation. Ce garde-fou reste en revanche
    pleinement actif sur la voie utilisateur normale.
    """

    async def _interdit(session: Any, entreprise_id: int) -> None:
        raise AssertionError(
            "La limite de plan ne doit pas être consultée par l'administration."
        )

    monkeypatch.setattr(abonnements_services, "ensure_can_add_active_user", _interdit)

    cible = _utilisateur(_CIBLE_ID, est_actif=False)
    session = _FakeSession({_CIBLE_ID: cible})

    resultat = await services.definir_activite_utilisateur(
        session,  # type: ignore[arg-type]
        _CIBLE_ID,
        True,
        _admin(),
    )

    assert resultat.est_actif is True


# ---------------------------------------------------------------------------
# Suppression d'une entreprise
# ---------------------------------------------------------------------------


async def test_entreprise_avec_facture_scellee_non_supprimable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Une facture émise rend la suppression **définitivement** impossible : 403 et
    non 409, pour signifier qu'aucune action préalable ne la débloquera.
    """
    _preparer_entreprise(
        monkeypatch,
        CompteursEntreprise(factures_total=1, factures_scellees=1),
    )
    session = _FakeSession(
        {_ENTREPRISE_ID: Entreprise(id=_ENTREPRISE_ID, nom_entreprise="ACME")}
    )

    with pytest.raises(HTTPException) as exc:
        await services.supprimer_entreprise(session, _ENTREPRISE_ID)  # type: ignore[arg-type]

    assert exc.value.status_code == status.HTTP_403_FORBIDDEN
    assert session.commits == 0
    assert session.executions == 0


async def test_entreprise_avec_donnees_non_scellees_refusee(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Des données non réglementaires (brouillons, clients) bloquent en 409 : la
    suppression redevient possible une fois ces données retirées.
    """
    _preparer_entreprise(
        monkeypatch,
        CompteursEntreprise(factures_total=2, factures_brouillon=2, clients=3),
    )
    session = _FakeSession(
        {_ENTREPRISE_ID: Entreprise(id=_ENTREPRISE_ID, nom_entreprise="ACME")}
    )

    with pytest.raises(HTTPException) as exc:
        await services.supprimer_entreprise(session, _ENTREPRISE_ID)  # type: ignore[arg-type]

    assert exc.value.status_code == status.HTTP_409_CONFLICT
    assert "brouillon" in exc.value.detail
    assert session.commits == 0


async def test_entreprise_vide_supprimable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Une entreprise vierge (doublon, test, inscription abandonnée) est supprimée."""
    _preparer_entreprise(monkeypatch, CompteursEntreprise())
    session = _FakeSession(
        {_ENTREPRISE_ID: Entreprise(id=_ENTREPRISE_ID, nom_entreprise="ACME")}
    )

    await services.supprimer_entreprise(session, _ENTREPRISE_ID)  # type: ignore[arg-type]

    assert session.commits == 1
    # Traces détachées, rattachements et souscriptions retirés, entreprise supprimée.
    assert session.executions == 6


async def test_entreprise_introuvable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un identifiant inconnu renvoie 404, jamais une erreur serveur."""
    _preparer_entreprise(monkeypatch, CompteursEntreprise())
    session = _FakeSession({})

    with pytest.raises(HTTPException) as exc:
        await services.supprimer_entreprise(session, 999)  # type: ignore[arg-type]

    assert exc.value.status_code == status.HTTP_404_NOT_FOUND
