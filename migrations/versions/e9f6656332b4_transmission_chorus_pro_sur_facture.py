"""transmission chorus pro sur facture

Revision ID: e9f6656332b4
Revises: d5a71c93b0e4
Create Date: 2026-07-30 19:44:12.888947

Ajoute sur `facture` les métadonnées de transmission à Chorus Pro :
`numero_flux_depot_chorus` (identifiant du flux attribué lors d'un dépôt
accepté) et `date_transmission_chorus`. Colonnes nullables : les factures
existantes restent non transmises. Le statut de cycle de vie et son
historique passent par `id_statut` et `evenement_pdp` (tables existantes).
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e9f6656332b4"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "d5a71c93b0e4"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "facture",
        sa.Column(
            "numero_flux_depot_chorus",
            sqlmodel.sql.sqltypes.AutoString(length=50),
            nullable=True,
        ),
    )
    op.add_column(
        "facture",
        sa.Column("date_transmission_chorus", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("facture", "date_transmission_chorus")
    op.drop_column("facture", "numero_flux_depot_chorus")
