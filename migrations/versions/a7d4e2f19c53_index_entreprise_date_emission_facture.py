"""index composite entreprise + date emission sur facture

Revision ID: a7d4e2f19c53
Revises: 9f2c41d7b8a3
Create Date: 2026-07-28 10:12:44.318207

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7d4e2f19c53"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "9f2c41d7b8a3"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Ajoute l'index composite (id_entreprise, date_emission) sur facture.

    Les agrégations de la route de statistiques — comme la liste filtrée par
    période — sélectionnent toujours une entreprise puis une plage de dates
    d'émission. Avec le seul index sur `id_entreprise`, le moteur ramène
    toutes les factures du tenant avant de filtrer les dates ligne à ligne :
    coût proportionnel à l'historique complet. L'index composite borne la
    lecture à la période demandée.
    """
    op.create_index(
        "ix_facture_entreprise_date_emission",
        "facture",
        ["id_entreprise", "date_emission"],
        unique=False,
    )


def downgrade() -> None:
    """Retire l'index composite ; l'index simple sur id_entreprise subsiste."""
    op.drop_index("ix_facture_entreprise_date_emission", table_name="facture")
