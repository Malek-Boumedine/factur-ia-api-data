from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


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

    pass


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


class ClientRead(ClientBase):
    """
    Schéma pour renvoyer les données du client au front-end.
    """

    id: int
    id_abonnement: int
    id_createur: int
    id_modificateur: int | None = None

    date_creation: datetime
    date_modification: datetime
    date_desactivation: datetime | None = None

    model_config = ConfigDict(from_attributes=True)
