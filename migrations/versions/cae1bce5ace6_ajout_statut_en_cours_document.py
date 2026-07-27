"""ajout statut en_cours document

Revision ID: cae1bce5ace6
Revises: c40f5ade005f
Create Date: 2026-07-20 22:52:20.466992

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "cae1bce5ace6"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "c40f5ade005f"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Ajoute la valeur EN_COURS à l'énumération des statuts de document."""
    op.alter_column(
        "document",
        "statut",
        existing_type=sa.Enum("EN_ATTENTE", "TRAITE", "ERREUR", name="statutdocument"),
        type_=sa.Enum(
            "EN_ATTENTE", "EN_COURS", "TRAITE", "ERREUR", name="statutdocument"
        ),
        existing_nullable=False,
    )


def downgrade() -> None:
    """Retire EN_COURS ; les documents concernés reviennent en EN_ATTENTE."""
    op.execute("UPDATE document SET statut = 'EN_ATTENTE' WHERE statut = 'EN_COURS'")
    op.alter_column(
        "document",
        "statut",
        existing_type=sa.Enum(
            "EN_ATTENTE", "EN_COURS", "TRAITE", "ERREUR", name="statutdocument"
        ),
        type_=sa.Enum("EN_ATTENTE", "TRAITE", "ERREUR", name="statutdocument"),
        existing_nullable=False,
    )
