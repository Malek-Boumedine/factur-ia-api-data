"""ajout type_document et par_champ sur extraction_ocr

Revision ID: 9f2c41d7b8a3
Revises: 521bccc8aa62
Create Date: 2026-07-27 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9f2c41d7b8a3"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "521bccc8aa62"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Ajoute les métadonnées d'analyse IA sur l'extraction OCR (additif).

    `type_document` : type détecté par l'IA (devis, facture, avoir, inconnu).
    `par_champ` : scores de confiance par champ extrait, en chaînes telles que
    reçues du contrat (précision Decimal préservée). Null = non calculé
    (échec d'extraction ou version antérieure de l'API IA).
    """
    op.add_column(
        "extraction_ocr",
        sa.Column("type_document", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "extraction_ocr",
        sa.Column("par_champ", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    """Retire les deux colonnes ; les métadonnées d'analyse sont perdues."""
    op.drop_column("extraction_ocr", "par_champ")
    op.drop_column("extraction_ocr", "type_document")
