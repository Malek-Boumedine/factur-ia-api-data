from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UtilisateurBase(BaseModel):
    nom: str = Field(..., max_length=255)
    prenom: str = Field(..., max_length=255)
    adresse: str = Field(..., max_length=255)
    adresse_complement: str | None = Field(default=None, max_length=255)
    code_postal: str = Field(..., max_length=10)
    ville: str = Field(..., max_length=150)
    email: EmailStr = Field(..., max_length=255)
    telephone: str | None = Field(default=None, max_length=20)
    est_actif: bool = Field(default=True)


class UtilisateurCreate(UtilisateurBase):
    """Schéma pour créer un utilisateur avec son mot de passe en clair."""

    password: str = Field(..., min_length=8, description="Mot de passe en clair")


class UtilisateurUpdate(BaseModel):
    """Schéma pour la mise à jour partielle d'un utilisateur."""

    nom: str | None = None
    prenom: str | None = None
    adresse: str | None = None
    adresse_complement: str | None = None
    code_postal: str | None = Field(default=None, max_length=10)
    ville: str | None = Field(default=None, max_length=150)
    email: EmailStr | None = None
    telephone: str | None = None
    est_actif: bool | None = None


class UtilisateurRead(UtilisateurBase):
    """Schéma de sortie (le hash n'est jamais renvoyé)."""

    id: int
    date_creation: datetime
    date_modification: datetime
    date_derniere_connexion: datetime | None = None

    model_config = ConfigDict(from_attributes=True)
