from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UtilisateurBase(BaseModel):
    nom: str = Field(..., max_length=255)
    prenom: str = Field(..., max_length=255)
    adresse: str | None = Field(default=None, max_length=255)
    adresse_complement: str | None = Field(default=None, max_length=255)
    code_postal: str | None = Field(default=None, max_length=10)
    ville: str | None = Field(default=None, max_length=150)
    email: EmailStr = Field(..., max_length=255)
    telephone: str | None = Field(default=None, max_length=20)
    est_actif: bool = Field(default=True)


class UtilisateurCreate(UtilisateurBase):
    """Schéma pour créer un utilisateur avec son mot de passe en clair."""

    password: str = Field(..., min_length=8, description="Mot de passe en clair")
    id_role: int = Field(..., description="ID du rôle métier rattaché")
    est_admin: bool = Field(
        default=False, description="Droit admin au niveau de l'entreprise"
    )


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
    admin_plateforme: bool = Field(
        default=False,
        description="Statut administrateur global de la plateforme (lecture seule).",
    )
    role: str | None = None
    est_admin: bool | None = Field(
        default=None,
        description=(
            "Statut administrateur du membre dans l'entreprise active. "
            "Lecture seule : à utiliser pour pré-remplir le formulaire d'édition "
            "et éviter de retirer les droits par erreur."
        ),
    )

    model_config = ConfigDict(from_attributes=True)


class AdminPlateformeRead(BaseModel):
    """
    Schéma de lecture d'un administrateur de plateforme.

    Volontairement distinct de `UtilisateurRead` : ne contient que les champs
    globaux (pas de `role`/`est_admin`, qui dépendent d'une entreprise).
    """

    id: int
    nom: str
    prenom: str
    email: EmailStr
    est_actif: bool
    admin_plateforme: bool
    compte_protege: bool
    date_creation: datetime

    model_config = ConfigDict(from_attributes=True)


class UtilisateurTeamUpdate(UtilisateurUpdate):
    """
    Hérite de tous les champs optionnels (nom, prenom, adresse...) de UtilisateurUpdate,
    et y ajoute les champs de gestion réservés aux administrateurs.
    """

    password: str | None = Field(default=None, min_length=8)
    id_role: int | None = Field(default=None)
    est_admin: bool | None = Field(default=None)
