"""Tests du chiffrement au repos et du masquage de l'IBAN de facture.

Couvre le type ``EncryptedStr`` (aller-retour transparent via l'ORM, token
Fernet illisible en lecture SQL brute, erreur explicite si la clé ne
correspond pas), le masquage dans les réponses API, la protection contre
l'écho du masque (PATCH = inchangé, création = 422), le masquage de l'IBAN
dans ``extraction_ocr.contenu_brut``, les helpers de la migration (chiffre
l'existant, idempotence, downgrade) et la validation de la clé au démarrage.
"""

import importlib.util
import json
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from pydantic import ValidationError
from pytest import MonkeyPatch
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine
from src.auth.dependencies import get_current_user, verify_tenant_access
from src.core.config import Settings
from src.core.crypto import (
    FERNET_TOKEN_PREFIX,
    DechiffrementError,
    encrypt_value,
    is_masked,
    mask_iban,
)
from src.core.database import get_session
from src.documents.schemas import OcrWebhookPayload
from src.documents.service import _contenu_brut_masque
from src.factures.models import Facture, FactureLigne, StatutFacture
from src.factures.router import router as factures_router
from src.factures.schemas import FactureRead
from src.utilisateurs.models import Utilisateur

IBAN_CLAIR = "FR7630006000011234567890189"
IBAN_MASQUE = "FR76 •••• •••• •••• •••• •••0 189"


# ---------------------------------------------------------------------------
# Masquage (fonctions pures)
# ---------------------------------------------------------------------------


def test_mask_iban_garde_4_premiers_et_4_derniers() -> None:
    assert mask_iban(IBAN_CLAIR) == IBAN_MASQUE


def test_mask_iban_ignore_le_format_d_entree() -> None:
    """Un IBAN déjà groupé par espaces produit le même masque."""
    assert mask_iban("FR76 3000 6000 0112 3456 7890 189") == IBAN_MASQUE


def test_mask_iban_valeurs_courtes() -> None:
    """Jamais plus de 8 caractères réels visibles, même sur valeur atypique."""
    assert mask_iban("FR7612") == "••76 12"
    assert mask_iban("FR12") == "••••"


def test_is_masked() -> None:
    assert is_masked(IBAN_MASQUE)
    assert not is_masked(IBAN_CLAIR)


# ---------------------------------------------------------------------------
# EncryptedStr : chiffrement transparent via l'ORM
# ---------------------------------------------------------------------------


@pytest.fixture
def engine() -> Iterator[Engine]:
    """Base SQLite en mémoire avec le schéma complet des modèles."""
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    yield engine
    engine.dispose()


def _facture(**overrides: Any) -> Facture:
    defaults: dict[str, Any] = {
        "id_entreprise": 1,
        "id_createur": 1,
        "numero_facture": "FAC-202607-0001",
        "id_statut": 1,
        "total_ht": Decimal("100.00"),
        "total_tva": Decimal("20.00"),
        "total_ttc": Decimal("120.00"),
    }
    defaults.update(overrides)
    return Facture(**defaults)


def test_aller_retour_transparent(engine: Engine) -> None:
    """L'ORM écrit et relit l'IBAN en clair : le chiffrement est invisible."""
    with Session(engine) as session:
        session.add(_facture(iban=IBAN_CLAIR))
        session.commit()

    with Session(engine) as session:
        facture = session.get(Facture, 1)
        assert facture is not None
        assert facture.iban == IBAN_CLAIR


def test_valeur_illisible_en_base(engine: Engine) -> None:
    """En SQL brut (dump), la colonne ne contient qu'un token Fernet."""
    with Session(engine) as session:
        session.add(_facture(iban=IBAN_CLAIR))
        session.commit()

    with engine.connect() as conn:
        brut = conn.execute(sa.text("SELECT iban FROM facture")).scalar_one()

    assert brut != IBAN_CLAIR
    assert IBAN_CLAIR not in brut
    assert brut.startswith(FERNET_TOKEN_PREFIX)


def test_iban_null_reste_null(engine: Engine) -> None:
    with Session(engine) as session:
        session.add(_facture(iban=None))
        session.commit()

    with engine.connect() as conn:
        brut = conn.execute(sa.text("SELECT iban FROM facture")).scalar_one()
    assert brut is None


def test_dechiffrement_impossible_erreur_explicite(engine: Engine) -> None:
    """Token forgé avec une autre clé : erreur explicite, jamais la valeur brute."""
    with Session(engine) as session:
        session.add(_facture(iban=IBAN_CLAIR))
        session.commit()

    with engine.connect() as conn:
        conn.execute(
            sa.text("UPDATE facture SET iban = :iban"),
            {"iban": FERNET_TOKEN_PREFIX + "corrompu-pas-un-vrai-token"},
        )
        conn.commit()

    with Session(engine) as session:
        with pytest.raises(DechiffrementError):
            session.get(Facture, 1)


# ---------------------------------------------------------------------------
# Masquage dans les réponses API
# ---------------------------------------------------------------------------


def test_facture_read_masque_l_iban() -> None:
    facture = _facture(id=1, iban=IBAN_CLAIR)
    body = FactureRead.model_validate(facture).model_dump()
    assert body["iban"] == IBAN_MASQUE
    assert IBAN_CLAIR not in FactureRead.model_validate(facture).model_dump_json()


def test_facture_read_iban_absent() -> None:
    facture = _facture(id=1, iban=None)
    assert FactureRead.model_validate(facture).model_dump()["iban"] is None


# ---------------------------------------------------------------------------
# Routes : écho du masque et lecture masquée (doublure de session)
# ---------------------------------------------------------------------------


class _Result:
    def __init__(self, value: Any) -> None:
        self._value = value

    def first(self) -> Any:
        return self._value


class _FakeSession:
    """Session factice : dépile des résultats prévus."""

    def __init__(self, results: list[Any]) -> None:
        self._results = results

    async def exec(self, statement: Any) -> _Result:
        return _Result(self._results.pop(0))

    def add(self, obj: Any) -> None:
        pass

    async def delete(self, obj: Any) -> None:
        pass

    async def flush(self) -> None:
        pass

    async def commit(self) -> None:
        pass


def _facture_brouillon(iban: str | None = IBAN_CLAIR) -> Facture:
    facture = _facture(id=42, id_client=7, iban=iban)
    facture.statut_ref = StatutFacture(id=1, libelle="Brouillon")
    facture.lignes = [
        FactureLigne(
            id=1,
            id_facture=42,
            ordre=0,
            designation="Prestation",
            quantite=Decimal("1.000"),
            prix_unitaire_ht=Decimal("100.00"),
            id_taux_tva=1,
            montant_ht=Decimal("100.00"),
            montant_tva=Decimal("20.00"),
            montant_ttc=Decimal("120.00"),
        )
    ]
    return facture


def _app(session: _FakeSession) -> FastAPI:
    app = FastAPI()
    app.include_router(factures_router)
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: Utilisateur(
        id=1,
        nom="Test",
        prenom="User",
        email="user@example.com",
        hash_mot_de_passe="x",  # pragma: allowlist secret
    )
    app.dependency_overrides[verify_tenant_access] = lambda: 1
    return app


async def _patch(app: FastAPI, payload: dict[str, Any]) -> Response:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.patch("/factures/42", json=payload)


async def test_patch_masque_ne_change_pas_l_iban() -> None:
    """Le front réexpédie le masque tel quel : la vraie valeur est préservée."""
    facture = _facture_brouillon()
    session = _FakeSession([facture, facture])
    response = await _patch(_app(session), {"iban": IBAN_MASQUE, "notes": "maj"})

    assert response.status_code == 200
    assert facture.iban == IBAN_CLAIR
    assert facture.notes == "maj"
    # La réponse elle-même ne contient que le masque
    assert response.json()["iban"] == IBAN_MASQUE


async def test_patch_nouvel_iban_applique_et_masque_en_reponse() -> None:
    facture = _facture_brouillon()
    session = _FakeSession([facture, facture])
    nouvel_iban = "DE89370400440532013000"
    response = await _patch(_app(session), {"iban": nouvel_iban})

    assert response.status_code == 200
    assert facture.iban == nouvel_iban
    assert nouvel_iban not in response.text


async def test_patch_null_efface_l_iban() -> None:
    """Un ``null`` explicite reste un effacement volontaire (pas un masque)."""
    facture = _facture_brouillon()
    session = _FakeSession([facture, facture])
    response = await _patch(_app(session), {"iban": None})

    assert response.status_code == 200
    assert facture.iban is None


async def test_creation_avec_iban_masque_422() -> None:
    """À la création, aucun IBAN à préserver : le masque est un bug du front."""
    transport = ASGITransport(app=_app(_FakeSession([])))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/factures/",
            json={
                "iban": IBAN_MASQUE,
                "lignes": [
                    {
                        "designation": "Prestation",
                        "quantite": "1.000",
                        "prix_unitaire_ht": "100.00",
                        "id_taux_tva": 1,
                    }
                ],
            },
        )

    assert response.status_code == 422
    assert "IBAN masqué" in response.text


# ---------------------------------------------------------------------------
# Callback OCR : contenu_brut archivé sans IBAN en clair
# ---------------------------------------------------------------------------


def _payload_ocr(iban: str | None) -> OcrWebhookPayload:
    return OcrWebhookPayload(
        id_document=1,
        score_confiance=Decimal("0.95"),
        iban=iban,
        total_ht=Decimal("100.00"),
        total_tva=Decimal("20.00"),
        total_ttc=Decimal("120.00"),
    )


def test_contenu_brut_iban_masque() -> None:
    contenu = _contenu_brut_masque(_payload_ocr(IBAN_CLAIR))
    assert contenu["iban"] == IBAN_MASQUE
    assert IBAN_CLAIR not in json.dumps(contenu)
    # Le reste du payload est archivé intact
    assert contenu["total_ttc"] == "120.00"


def test_contenu_brut_sans_iban() -> None:
    assert _contenu_brut_masque(_payload_ocr(None))["iban"] is None


# ---------------------------------------------------------------------------
# Helpers de la migration (schéma + données)
# ---------------------------------------------------------------------------

_MIGRATION_PATH = (
    Path(__file__).resolve().parent.parent
    / "migrations"
    / "versions"
    / "f4b8c2d91e07_chiffrement_iban_facture_au_repos.py"
)


@pytest.fixture
def migration() -> Any:
    """Module de la migration chargé depuis son fichier (hors package)."""
    spec = importlib.util.spec_from_file_location("migration_iban", _MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def bind() -> Iterator[sa.Connection]:
    """Connexion SQLite avec les tables minimales visées par la migration."""
    engine = sa.create_engine("sqlite://")
    with engine.connect() as conn:
        conn.execute(
            sa.text("CREATE TABLE facture (id INTEGER PRIMARY KEY, iban VARCHAR(255))")
        )
        conn.execute(
            sa.text(
                "CREATE TABLE extraction_ocr "
                "(id INTEGER PRIMARY KEY, contenu_brut TEXT)"
            )
        )
        yield conn
    engine.dispose()


def _ibans_en_base(bind: sa.Connection) -> dict[int, str | None]:
    rows = bind.execute(sa.text("SELECT id, iban FROM facture")).all()
    return {row[0]: row[1] for row in rows}


def test_migration_chiffre_l_existant_et_est_idempotente(
    migration: Any, bind: sa.Connection
) -> None:
    deja_chiffre = encrypt_value("DE89370400440532013000")
    bind.execute(
        sa.text(
            "INSERT INTO facture (id, iban) VALUES (1, :clair), (2, :token), (3, NULL)"
        ),
        {"clair": IBAN_CLAIR, "token": deja_chiffre},
    )

    migration._encrypt_facture_ibans(bind)
    apres = _ibans_en_base(bind)
    assert apres[1] is not None and apres[1].startswith(FERNET_TOKEN_PREFIX)
    assert apres[1] != IBAN_CLAIR
    # Une valeur déjà chiffrée n'est pas rechiffrée, le NULL reste NULL
    assert apres[2] == deja_chiffre
    assert apres[3] is None

    # Rejouer la migration ne double-chiffre pas
    migration._encrypt_facture_ibans(bind)
    assert _ibans_en_base(bind)[1] == apres[1]


def test_migration_downgrade_restitue_le_clair(
    migration: Any, bind: sa.Connection
) -> None:
    bind.execute(
        sa.text("INSERT INTO facture (id, iban) VALUES (1, :clair)"),
        {"clair": IBAN_CLAIR},
    )
    migration._encrypt_facture_ibans(bind)
    migration._decrypt_facture_ibans(bind)
    assert _ibans_en_base(bind)[1] == IBAN_CLAIR


def test_migration_masque_contenu_brut(migration: Any, bind: sa.Connection) -> None:
    bind.execute(
        sa.text(
            "INSERT INTO extraction_ocr (id, contenu_brut) VALUES "
            "(1, :avec_iban), (2, :sans_iban), (3, NULL)"
        ),
        {
            "avec_iban": json.dumps({"iban": IBAN_CLAIR, "total_ttc": "120.00"}),
            "sans_iban": json.dumps({"iban": None, "total_ttc": "50.00"}),
        },
    )

    migration._mask_contenu_brut_ibans(bind)

    rows = bind.execute(
        sa.text("SELECT id, contenu_brut FROM extraction_ocr ORDER BY id")
    ).all()
    avec_iban = json.loads(rows[0][1])
    assert avec_iban["iban"] == IBAN_MASQUE
    assert avec_iban["total_ttc"] == "120.00"
    # Ligne sans IBAN et ligne NULL inchangées
    assert json.loads(rows[1][1]) == {"iban": None, "total_ttc": "50.00"}
    assert rows[2][1] is None

    # Idempotence : un masque déjà en place n'est pas retraité
    migration._mask_contenu_brut_ibans(bind)
    assert (
        json.loads(
            bind.execute(
                sa.text("SELECT contenu_brut FROM extraction_ocr WHERE id = 1")
            ).scalar_one()
        )
        == avec_iban
    )


# ---------------------------------------------------------------------------
# Validation de la clé au démarrage
# ---------------------------------------------------------------------------

_SETTINGS_KWARGS: dict[str, Any] = {
    "APP_NAME": "test",
    "ENVIRONNEMENT": "test",
    "DEBUG": False,
    "DB_HOST": "localhost",
    "DB_PORT": 3306,
    "DB_NAME": "test",
    "DB_USER": "test",
    "DB_PASSWORD": "test",  # pragma: allowlist secret
    "DB_CHARSET": "utf8mb4",
    "API_PORT": 8000,
    "API_HOST": "localhost",
    "ACCESS_TOKEN_EXPIRE_MINUTES": 30,
    "ALGORITHM": "HS256",
    "SECRET_KEY": "x",  # pragma: allowlist secret
    "SECRET_OCR_TOKEN": "x",  # pragma: allowlist secret
    "IA_API_BASE_URL": "http://ia-api.invalid",
}


def test_cle_absente_bloque_le_demarrage(monkeypatch: MonkeyPatch) -> None:
    """Sans IBAN_ENCRYPTION_KEY, les settings (donc l'app) ne se chargent pas."""
    monkeypatch.delenv("IBAN_ENCRYPTION_KEY", raising=False)
    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None, **_SETTINGS_KWARGS)
    assert "IBAN_ENCRYPTION_KEY" in str(exc_info.value)


def test_cle_invalide_message_explicite(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.delenv("IBAN_ENCRYPTION_KEY", raising=False)
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            _env_file=None,
            IBAN_ENCRYPTION_KEY="pas-une-cle-fernet",
            **_SETTINGS_KWARGS,
        )
    assert "clé Fernet valide" in str(exc_info.value)


def test_cle_valide_acceptee() -> None:
    from cryptography.fernet import Fernet

    settings = Settings(
        _env_file=None,
        IBAN_ENCRYPTION_KEY=Fernet.generate_key().decode(),
        **_SETTINGS_KWARGS,
    )
    assert settings.IBAN_ENCRYPTION_KEY
