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


class ProfilUpdate(BaseModel):
    """
    Mise à jour partielle du profil par l'utilisateur lui-même (self-update).

    Volontairement restreint : ni `email` (modifiable uniquement via l'endpoint
    dédié sécurisé `POST /utilisateurs/me/changer-email`, qui exige le mot de
    passe actuel) ni `est_actif` (un utilisateur ne peut pas se désactiver
    lui-même). Ces deux champs restent réservés à la voie admin
    (`UtilisateurTeamUpdate`).
    """

    nom: str | None = None
    prenom: str | None = None
    adresse: str | None = None
    adresse_complement: str | None = None
    code_postal: str | None = Field(default=None, max_length=10)
    ville: str | None = Field(default=None, max_length=150)
    telephone: str | None = None


class UtilisateurUpdate(BaseModel):
    """Schéma pour la mise à jour partielle d'un utilisateur (voie admin)."""

    nom: str | None = None
    prenom: str | None = None
    adresse: str | None = None
    adresse_complement: str | None = None
    code_postal: str | None = Field(default=None, max_length=10)
    ville: str | None = Field(default=None, max_length=150)
    email: EmailStr | None = None
    telephone: str | None = None
    est_actif: bool | None = None


class ChangementMotDePasseRequest(BaseModel):
    """
    Changement de mot de passe par un utilisateur connecté.

    Le mot de passe actuel est exigé pour re-vérifier l'identité avant tout
    changement (jamais de modification à l'aveugle sur une session ouverte). Le
    nouveau suit la même politique de robustesse que l'inscription et la
    réinitialisation (`min_length=8`).
    """

    mot_de_passe_actuel: str = Field(..., description="Mot de passe actuel en clair")
    nouveau_mot_de_passe: str = Field(
        ..., min_length=8, description="Nouveau mot de passe en clair"
    )


class ChangementEmailRequest(BaseModel):
    """
    Changement d'email par un utilisateur connecté.

    L'email étant l'identifiant de connexion, le mot de passe actuel est exigé
    pour re-vérifier l'identité avant tout changement (jamais de modification à
    l'aveugle sur une session ouverte).
    """

    mot_de_passe_actuel: str = Field(..., description="Mot de passe actuel en clair")
    nouvel_email: EmailStr = Field(..., max_length=255, description="Nouvel email")


class ChangementEmailResponse(BaseModel):
    """
    Réponse au changement d'email.

    L'email étant le `sub` du JWT, l'ancien token devient caduc dès le
    changement. On ré-émet donc un token frais (aligné sur le format du login)
    pour que la session se poursuive sans reconnexion.
    """

    message: str
    access_token: str = Field(..., description="Nouveau JWT à utiliser désormais")
    token_type: str = Field(default="bearer")


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
    compte_protege: bool = Field(
        default=False,
        description=(
            "Compte racine protégé : indestructible et non révocable. Lecture "
            "seule : à utiliser pour masquer préventivement l'action de suppression."
        ),
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
