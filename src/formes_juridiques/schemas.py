from pydantic import BaseModel, ConfigDict, Field


class FormeJuridiqueRead(BaseModel):
    """
    Schéma de lecture d'une forme juridique (donnée de référence globale,
    partagée par toutes les entreprises de la plateforme).
    """

    id: int
    code: str = Field(description="Code stable de la forme juridique (ex : SARL)")
    libelle: str = Field(
        description="Libellé affiché (ex : Société à responsabilité limitée)"
    )
    est_actif: bool = Field(
        description="Indique si la forme est proposée pour de nouvelles saisies"
    )

    model_config = ConfigDict(from_attributes=True)
