from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EntrepriseCreate(BaseModel):
    """Données d'onboarding pour créer un premier espace de travail."""

    nom_entreprise: str = Field(..., max_length=255)
    siret: str | None = Field(
        default=None,
        min_length=14,
        max_length=14,
        description="SIRET à 14 chiffres (optionnel).",
    )
    id_forme_juridique: int | None = Field(default=None)

    @field_validator("siret")
    @classmethod
    def _valider_siret(cls, valeur: str | None) -> str | None:
        """Vérifie que le SIRET, s'il est fourni, comporte 14 chiffres."""
        if valeur is None:
            return valeur
        if not valeur.isdigit() or len(valeur) != 14:
            raise ValueError("Le SIRET doit comporter exactement 14 chiffres.")
        return valeur


class EntrepriseRead(BaseModel):
    """Schéma de sortie d'une entreprise."""

    id: int
    nom_entreprise: str
    siret: str | None
    id_forme_juridique: int | None
    date_creation: datetime
    date_modification: datetime

    model_config = ConfigDict(from_attributes=True)
