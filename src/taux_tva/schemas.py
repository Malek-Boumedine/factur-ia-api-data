from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class TauxTvaBase(BaseModel):
    """
    Propriétés communes d'un taux de TVA (donnée de référence globale,
    partagée par toutes les entreprises de la plateforme).
    """

    taux: Decimal = Field(
        ...,
        ge=0,
        le=100,
        description="Valeur du taux en pourcentage (ex : 20.00). Unique.",
    )
    libelle: str = Field(
        ..., max_length=100, description="Libellé affiché (ex : Taux normal)"
    )
    code_comptable: str | None = Field(
        default=None, max_length=50, description="Code comptable associé (optionnel)"
    )
    est_actif: bool = Field(
        default=True,
        description="Indique si le taux est proposé pour de nouvelles saisies",
    )


class TauxTvaCreate(TauxTvaBase):
    """Schéma de création d'un taux de TVA (admin plateforme uniquement)."""

    pass


class TauxTvaUpdate(BaseModel):
    """
    Schéma de mise à jour partielle d'un taux de TVA (PATCH).
    Tous les champs sont optionnels ; `est_actif=true` permet de réactiver
    un taux désactivé.
    """

    taux: Decimal | None = Field(default=None, ge=0, le=100)
    libelle: str | None = Field(default=None, max_length=100)
    code_comptable: str | None = Field(default=None, max_length=50)
    est_actif: bool | None = None


class TauxTvaRead(TauxTvaBase):
    """Schéma de lecture d'un taux de TVA."""

    id: int

    model_config = ConfigDict(from_attributes=True)
