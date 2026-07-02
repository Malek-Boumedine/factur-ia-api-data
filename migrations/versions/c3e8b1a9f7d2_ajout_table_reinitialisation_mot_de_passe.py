"""ajout table reinitialisation_mot_de_passe (flux mot de passe oublié)

Revision ID: c3e8b1a9f7d2
Revises: b1f2a3c4d5e6
Create Date: 2026-07-01 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3e8b1a9f7d2"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "b1f2a3c4d5e6"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "reinitialisation_mot_de_passe",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("id_utilisateur", sa.Integer(), nullable=False),
        sa.Column(
            "token_hash",
            sqlmodel.sql.sqltypes.AutoString(length=64),
            nullable=False,
        ),
        sa.Column("date_expiration", sa.DateTime(), nullable=False),
        sa.Column("date_utilisation", sa.DateTime(), nullable=True),
        sa.Column("date_creation", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["id_utilisateur"],
            ["utilisateur.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_reinitialisation_mot_de_passe_id_utilisateur"),
        "reinitialisation_mot_de_passe",
        ["id_utilisateur"],
        unique=False,
    )
    op.create_index(
        op.f("ix_reinitialisation_mot_de_passe_token_hash"),
        "reinitialisation_mot_de_passe",
        ["token_hash"],
        unique=True,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        op.f("ix_reinitialisation_mot_de_passe_token_hash"),
        table_name="reinitialisation_mot_de_passe",
    )
    op.drop_index(
        op.f("ix_reinitialisation_mot_de_passe_id_utilisateur"),
        table_name="reinitialisation_mot_de_passe",
    )
    op.drop_table("reinitialisation_mot_de_passe")
