from pydantic import BaseModel, EmailStr, Field
from sqlmodel import SQLModel


class RoleRead(SQLModel):
    id: int
    libelle: str
    description: str | None = None


class MotDePasseOublieRequest(BaseModel):
    """Demande de réinitialisation : uniquement l'email du compte concerné."""

    email: EmailStr = Field(..., max_length=255)


class ReinitialisationRequest(BaseModel):
    """
    Réinitialisation effective : token reçu par email + nouveau mot de passe.

    Le nouveau mot de passe suit la même politique de robustesse que
    l'inscription (`min_length=8`).
    """

    token: str = Field(..., description="Token reçu dans le lien de réinitialisation")
    nouveau_mot_de_passe: str = Field(
        ..., min_length=8, description="Nouveau mot de passe en clair"
    )


class MessageResponse(BaseModel):
    """Réponse neutre générique (ne divulgue aucune information sensible)."""

    message: str
