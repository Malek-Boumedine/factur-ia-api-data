"""chiffrement iban facture au repos

Revision ID: f4b8c2d91e07
Revises: e9f6656332b4
Create Date: 2026-07-31

Chiffre l'IBAN de `facture` au repos (Fernet, clé `IBAN_ENCRYPTION_KEY`) :
élargit la colonne à VARCHAR(255) (un token Fernet fait ~140 caractères),
puis chiffre les IBAN existants en clair. Masque aussi l'IBAN dans les JSON
`extraction_ocr.contenu_brut` déjà stockés (archivage de diagnostic : le
clair n'y a plus sa place, la vraie valeur vit chiffrée sur la facture).

Idempotence : une valeur portant le préfixe Fernet (`gAAAA`) est considérée
déjà chiffrée et sautée ; un masque déjà présent dans `contenu_brut` n'est
pas retraité. La migration échoue explicitement si `IBAN_ENCRYPTION_KEY`
est absente ou invalide (validation des settings), sans toucher aux données.

Downgrade : déchiffre les IBAN de `facture` et rétrécit la colonne à
VARCHAR(34). Le masquage de `contenu_brut` est volontairement irréversible.

ATTENTION : perdre `IBAN_ENCRYPTION_KEY` rend les IBAN chiffrés
définitivement irrécupérables (et le downgrade impossible). La clé se
sauvegarde au même titre que les credentials de la base.
"""

import json
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from src.core.crypto import (
    FERNET_TOKEN_PREFIX,
    decrypt_value,
    encrypt_value,
    mask_iban,
)

# revision identifiers, used by Alembic.
revision: str = "f4b8c2d91e07"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "e9f6656332b4"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _encrypt_facture_ibans(bind: sa.Connection) -> None:
    """Chiffre les IBAN en clair de `facture` (les tokens Fernet sont sautés)."""
    rows = bind.execute(
        sa.text("SELECT id, iban FROM facture WHERE iban IS NOT NULL")
    ).all()
    for facture_id, iban in rows:
        if iban.startswith(FERNET_TOKEN_PREFIX):
            continue
        bind.execute(
            sa.text("UPDATE facture SET iban = :iban WHERE id = :id"),
            {"iban": encrypt_value(iban), "id": facture_id},
        )


def _decrypt_facture_ibans(bind: sa.Connection) -> None:
    """Restitue le clair dans `facture` (les valeurs non chiffrées sont sautées)."""
    rows = bind.execute(
        sa.text("SELECT id, iban FROM facture WHERE iban IS NOT NULL")
    ).all()
    for facture_id, iban in rows:
        if not iban.startswith(FERNET_TOKEN_PREFIX):
            continue
        bind.execute(
            sa.text("UPDATE facture SET iban = :iban WHERE id = :id"),
            {"iban": decrypt_value(iban), "id": facture_id},
        )


def _mask_contenu_brut_ibans(bind: sa.Connection) -> None:
    """Masque l'IBAN des payloads OCR archivés dans `extraction_ocr`."""
    rows = bind.execute(
        sa.text(
            "SELECT id, contenu_brut FROM extraction_ocr WHERE contenu_brut IS NOT NULL"
        )
    ).all()
    for extraction_id, contenu_brut in rows:
        # Colonne JSON : le driver renvoie une chaîne en SQL brut.
        contenu: Any = (
            json.loads(contenu_brut) if isinstance(contenu_brut, str) else contenu_brut
        )
        if not isinstance(contenu, dict):
            continue
        iban = contenu.get("iban")
        if not isinstance(iban, str) or not iban:
            continue
        masque = mask_iban(iban)
        if iban == masque:
            continue
        contenu["iban"] = masque
        bind.execute(
            sa.text("UPDATE extraction_ocr SET contenu_brut = :contenu WHERE id = :id"),
            {"contenu": json.dumps(contenu), "id": extraction_id},
        )


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column(
        "facture",
        "iban",
        existing_type=sa.String(length=34),
        type_=sa.String(length=255),
        existing_nullable=True,
    )
    bind = op.get_bind()
    _encrypt_facture_ibans(bind)
    _mask_contenu_brut_ibans(bind)


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    _decrypt_facture_ibans(bind)
    op.alter_column(
        "facture",
        "iban",
        existing_type=sa.String(length=255),
        type_=sa.String(length=34),
        existing_nullable=True,
    )
