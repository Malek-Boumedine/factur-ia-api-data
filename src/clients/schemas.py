from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from src.core.siret import validate_siret_flexible


class ClientBase(BaseModel):
    """
    Propriétés communes d'un client, partagées entre les différentes requêtes API.
    """

    raison_sociale: str = Field(
        ..., max_length=255, description="Nom ou raison sociale de l'entreprise"
    )
    siret: str | None = Field(
        default=None, max_length=14, description="Numéro SIRET à 14 chiffres"
    )
    numero_tva: str | None = Field(
        default=None, max_length=20, description="Numéro de TVA intracommunautaire"
    )
    adresse: str | None = Field(default=None, max_length=255)
    adresse_complement: str | None = Field(default=None, max_length=255)
    code_postal: str = Field(..., max_length=10)
    ville: str = Field(..., max_length=150)
    email: EmailStr | None = Field(default=None, max_length=255)
    telephone: str | None = Field(default=None, max_length=20)
    est_actif: bool = Field(default=True)


class ClientCreate(ClientBase):
    """
    Schéma pour la création d'un nouveau client.
    """

    @field_validator("siret", mode="before")
    @classmethod
    def normalize_siret(cls, value: object) -> object:
        """Séparateurs d'affichage retirés (espaces, points, tirets), chiffres
        uniquement. En mode ``before`` pour nettoyer avant ``max_length=14``.
        Chaîne vide ou séparateurs seuls = SIRET absent (``None``)."""
        return validate_siret_flexible(value)


class ClientUpdate(BaseModel):
    """
    Schéma pour la mise à jour partielle d'un client (PATCH).
    """

    raison_sociale: str | None = Field(default=None, max_length=255)
    siret: str | None = Field(default=None, max_length=14)
    numero_tva: str | None = Field(default=None, max_length=20)
    adresse: str | None = Field(default=None, max_length=255)
    adresse_complement: str | None = Field(default=None, max_length=255)
    code_postal: str | None = Field(default=None, max_length=10)
    ville: str | None = Field(default=None, max_length=150)
    email: EmailStr | None = Field(default=None, max_length=255)
    telephone: str | None = Field(default=None, max_length=20)
    est_actif: bool | None = Field(default=None)

    @field_validator("siret", mode="before")
    @classmethod
    def normalize_siret(cls, value: object) -> object:
        """Même normalisation qu'à la création (voir ``ClientCreate``)."""
        return validate_siret_flexible(value)


class ClientRead(ClientBase):
    """
    Schéma pour renvoyer les données du client au front-end.
    """

    id: int
    id_entreprise: int
    id_createur: int
    id_modificateur: int | None = None

    date_creation: datetime
    date_modification: datetime
    date_desactivation: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class SearchSireneSiretResponse(BaseModel):
    """
    Schéma représentant les données renvoyées
    par l'API gouvernementale lors d'une recherche par SIRET.
    Les champs sont alignés avec ClientBase pour
    faciliter le pré-remplissage côté front-end.
    """

    siret: str | None = Field(
        default=None, max_length=14, description="Numéro SIRET à 14 chiffres"
    )
    sirene: str | None = Field(
        default=None, max_length=9, description="Numéro SIRENE à 9 chiffres"
    )
    raison_sociale: str | None = Field(
        default=None,
        max_length=255,
        description="Nom ou raison sociale de l'entreprise",
    )
    adresse: str | None = Field(
        default=None, max_length=255, description="Numéro et voie du siège social"
    )
    code_postal: str | None = Field(default=None, max_length=10)
    ville: str | None = Field(default=None, max_length=150)
    numero_tva: str | None = Field(
        default=None, max_length=20, description="Numéro de TVA intracommunautaire"
    )
    activite_principale: str | None = Field(
        default=None, max_length=255, description="Activité principale de l'entreprise"
    )
    nom_dirigeant: str | None = Field(default=None, max_length=255)
    prenom_dirigeant: str | None = Field(default=None, max_length=255)
    type_dirigeant: str | None = Field(default=None, max_length=255)
