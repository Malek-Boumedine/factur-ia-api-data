from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.core.siret import validate_siret_strict


class EntrepriseCreate(BaseModel):
    """Données d'onboarding pour créer un premier espace de travail."""

    nom_entreprise: str = Field(..., max_length=255)
    siret: str | None = Field(
        default=None,
        min_length=14,
        max_length=14,
        description="SIRET à 14 chiffres (optionnel). Les séparateurs "
        "d'affichage (espaces, points, tirets) sont retirés automatiquement.",
    )
    id_forme_juridique: int | None = Field(default=None)

    @field_validator("siret", mode="before")
    @classmethod
    def _valider_siret(cls, valeur: object) -> object:
        """Normalise (séparateurs d'affichage retirés) puis exige 14 chiffres.

        En mode ``before`` : le nettoyage doit précéder les contraintes
        ``min_length``/``max_length`` du champ.
        """
        return validate_siret_strict(valeur)


class EntrepriseRead(BaseModel):
    """Schéma de sortie d'une entreprise."""

    id: int
    nom_entreprise: str
    siret: str | None
    id_forme_juridique: int | None
    date_creation: datetime
    date_modification: datetime

    model_config = ConfigDict(from_attributes=True)
