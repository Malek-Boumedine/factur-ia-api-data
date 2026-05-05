from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
from jose import jwt

from src.core.config import settings


def get_password_hash(password: str) -> str:
    """Génère un hash sécurisé à partir d'un mot de passe."""
    pwd_bytes = password.encode("utf-8")
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(pwd_bytes, salt)
    return str(hashed.decode("utf-8"))


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Vérifie la correspondance entre le clair et le hash."""
    try:
        password_bytes = plain_password.encode("utf-8")
        hashed_bytes = hashed_password.encode("utf-8")
        return bool(bcrypt.checkpw(password_bytes, hashed_bytes))
    except Exception:
        return False


def create_access_token(
    data: dict[str, Any], expires_delta: timedelta | None = None
) -> str:
    """Crée un token JWT d'accès."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
    else:
        expire = datetime.now(UTC) + timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )

    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(
        to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM
    )
    return str(encoded_jwt)


if __name__ == "__main__":
    # print(get_password_hash("azerty"))
    print(
        verify_password(
            "azerty", "$2b$12$10gR8ovMUn9x.OR6lbfjY.xgL6Rvu5q5eEo7W3bSP3l3uhaLjUps2"
        )
    )
