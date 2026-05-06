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
    id_ville: int | None = Field(
        default=None, description="Clé étrangère vers la table Ville"
    )
    email: EmailStr | None = Field(default=None, max_length=255)
    telephone: str | None = Field(default=None, max_length=20)
    est_actif: bool = Field(default=True)


class ClientCreate(ClientBase):
    """
    Schéma pour la création d'un nouveau client.
    Les champs id_abonnement et id_createur sont exclus ici car ils sont
    injectés de manière sécurisée par le backend (dépendances).
    """

    pass


class ClientUpdate(BaseModel):
    """
    Schéma pour la mise à jour partielle d'un client (PATCH).
    Tous les champs sont optionnels pour permettre de modifier une seule valeur.
    """

    raison_sociale: str | None = Field(default=None, max_length=255)
    siret: str | None = Field(default=None, max_length=14)
    numero_tva: str | None = Field(default=None, max_length=20)
    adresse: str | None = Field(default=None, max_length=255)
    adresse_complement: str | None = Field(default=None, max_length=255)
    id_ville: int | None = Field(default=None)
    email: EmailStr | None = Field(default=None, max_length=255)
    telephone: str | None = Field(default=None, max_length=20)
    est_actif: bool | None = Field(default=None)


class ClientRead(ClientBase):
    """
    Schéma pour renvoyer les données du client au front-end.
    Inclut les champs générés par la base de données (IDs, dates).
    """

    id: int
    id_abonnement: int
    id_createur: int
    id_modificateur: int | None = None

    date_creation: datetime
    date_modification: datetime
    date_desactivation: datetime | None = None

    # ConfigDict(from_attributes=True) permet à Pydantic de lire les données
    # directement depuis l'objet SQLModel (Base de données) vers le JSON
    model_config = ConfigDict(from_attributes=True)
