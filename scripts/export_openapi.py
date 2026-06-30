"""Exporte   vers ``contracts/openapi.json``.

Source de vérité : le code FastAPI (``src/main.py``). Ce script régénère
l'artefact versionné consommé par le repo ``factur-ia-web-django`` pour générer
son client typé. Ne jamais éditer ``contracts/openapi.json`` à la main.

Usage : ``uv run python scripts/export_openapi.py``
"""

import json
from pathlib import Path

from src.main import app

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONTRACT_PATH = PROJECT_ROOT / "contracts" / "openapi.json"


def export_openapi() -> Path:
    """Génère le schéma OpenAPI et l'écrit dans le fichier de contrat versionné."""
    CONTRACT_PATH.parent.mkdir(parents=True, exist_ok=True)
    schema = app.openapi()
    CONTRACT_PATH.write_text(
        json.dumps(schema, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return CONTRACT_PATH


if __name__ == "__main__":
    path = export_openapi()
    print(f"OpenAPI exporté vers {path.relative_to(PROJECT_ROOT)}")
