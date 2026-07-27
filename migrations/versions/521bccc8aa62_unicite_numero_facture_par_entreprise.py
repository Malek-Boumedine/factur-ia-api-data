"""unicite numero facture par entreprise

Revision ID: 521bccc8aa62
Revises: cae1bce5ace6
Create Date: 2026-07-27 13:21:39.071898

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "521bccc8aa62"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "cae1bce5ace6"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Remplace l'unicité globale de numero_facture par une unicité par entreprise.

    La numérotation étant calculée par entreprise, deux entreprises peuvent
    légitimement porter le même numéro dans leurs séries respectives : l'index
    unique global est remplacé par une contrainte composite
    (id_entreprise, numero_facture). L'index simple sur numero_facture est
    conservé pour les recherches par numéro seul.
    """
    op.drop_index("ix_facture_numero_facture", table_name="facture")
    op.create_index(
        "ix_facture_numero_facture", "facture", ["numero_facture"], unique=False
    )
    op.create_unique_constraint(
        "unique_entreprise_numero_facture",
        "facture",
        ["id_entreprise", "numero_facture"],
    )


def downgrade() -> None:
    """Restaure l'index unique global sur numero_facture.

    Limite attendue : échoue si des doublons inter-entreprises de
    numero_facture ont été créés après la migration (scénario nominal que la
    contrainte composite autorise volontairement). Il faut alors renuméroter
    les factures en conflit avant de rejouer le downgrade.
    """
    op.drop_constraint("unique_entreprise_numero_facture", "facture", type_="unique")
    op.drop_index("ix_facture_numero_facture", table_name="facture")
    op.create_index(
        "ix_facture_numero_facture", "facture", ["numero_facture"], unique=True
    )
