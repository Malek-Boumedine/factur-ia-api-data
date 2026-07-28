"""ajout de la suspension d'entreprise (est_actif, date et motif)

Revision ID: d5a71c93b0e4
Revises: 7f9225428d10
Create Date: 2026-07-28 10:12:00.000000

Ajoute l'état de suspension d'une entreprise, piloté par les administrateurs de
plateforme. `est_actif` porte l'état d'accès (une entreprise suspendue est
refusée par `verify_tenant_access`) ; `date_suspension` et `motif_suspension`
tracent la décision pour le support.

Les entreprises existantes restent actives (`server_default` à vrai), sans
suspension enregistrée.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d5a71c93b0e4"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "7f9225428d10"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "entreprise",
        sa.Column("est_actif", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "entreprise",
        sa.Column("date_suspension", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "entreprise",
        sa.Column("motif_suspension", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("entreprise", "motif_suspension")
    op.drop_column("entreprise", "date_suspension")
    op.drop_column("entreprise", "est_actif")
