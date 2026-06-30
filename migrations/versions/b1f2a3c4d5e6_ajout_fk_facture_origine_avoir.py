"""ajout FK id_facture_origine sur facture (lien avoir -> facture d'origine)

Revision ID: b1f2a3c4d5e6
Revises: ccff707cdb81
Create Date: 2026-06-30 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b1f2a3c4d5e6"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "ccff707cdb81"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "facture",
        sa.Column("id_facture_origine", sa.Integer(), nullable=True),
    )
    op.create_index(
        op.f("ix_facture_id_facture_origine"),
        "facture",
        ["id_facture_origine"],
        unique=False,
    )
    op.create_foreign_key(
        op.f("facture_id_facture_origine_fkey"),
        "facture",
        "facture",
        ["id_facture_origine"],
        ["id"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        op.f("facture_id_facture_origine_fkey"),
        "facture",
        type_="foreignkey",
    )
    op.drop_index(op.f("ix_facture_id_facture_origine"), table_name="facture")
    op.drop_column("facture", "id_facture_origine")
