from sqlmodel import SQLModel


class RoleRead(SQLModel):
    id: int
    libelle: str
    description: str | None = None
