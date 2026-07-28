"""unicite siret et numero tva client par entreprise

Revision ID: 7f9225428d10
Revises: a7d4e2f19c53
Create Date: 2026-07-28 13:58:39.731319

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7f9225428d10"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "a7d4e2f19c53"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Remplace l'unicité globale de siret et numero_tva par une unicité par entreprise.

    Chaque entreprise ayant son propre référentiel client, deux entreprises
    peuvent légitimement facturer le même client (même SIRET, même numéro de
    TVA). Les unicités globales sont remplacées par des contraintes composites
    (id_entreprise, colonne), sur le modèle du fix numero_facture. L'index
    simple sur siret est conservé pour les recherches par SIRET seul.
    """
    op.drop_index("ix_client_siret", table_name="client")
    op.create_index("ix_client_siret", "client", ["siret"], unique=False)
    op.create_unique_constraint(
        "unique_entreprise_siret", "client", ["id_entreprise", "siret"]
    )
    # Contrainte créée sans nom explicite dans la migration initiale :
    # MySQL l'a nommée d'après sa colonne, `numero_tva`.
    op.drop_constraint("numero_tva", "client", type_="unique")
    op.create_unique_constraint(
        "unique_entreprise_numero_tva", "client", ["id_entreprise", "numero_tva"]
    )


def downgrade() -> None:
    """Restaure les unicités globales sur siret et numero_tva.

    Limite attendue : échoue si des doublons inter-entreprises de siret ou de
    numero_tva ont été créés après la migration (scénario nominal que les
    contraintes composites autorisent volontairement). Il faut alors supprimer
    les clients en conflit avant de rejouer le downgrade.
    """
    op.drop_constraint("unique_entreprise_numero_tva", "client", type_="unique")
    op.create_unique_constraint("numero_tva", "client", ["numero_tva"])
    op.drop_constraint("unique_entreprise_siret", "client", type_="unique")
    op.drop_index("ix_client_siret", table_name="client")
    op.create_index("ix_client_siret", "client", ["siret"], unique=True)
