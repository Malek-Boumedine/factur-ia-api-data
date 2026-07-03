"""Configuration commune des tests.

`src.core.config` instancie `Settings()` au niveau module : sans variables
d'environnement ni fichier `.env`, l'import échoue (champs requis manquants) et
la collecte pytest s'interrompt — c'est le cas en CI, où `.env` est absent.

Ce `conftest.py` est importé par pytest avant les modules de test. Il charge des
valeurs factices depuis `.env.test` **uniquement** lorsqu'aucun vrai `.env`
n'est présent : en local le `.env` réel prime et le comportement reste inchangé,
en CI les valeurs bidon permettent l'import sans exposer de secret.
"""

from pathlib import Path

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# En local, un vrai `.env` existe : on n'y touche pas. En CI, il est absent : on
# fournit la config de test factice avant tout import de `src.core.config`.
if not (_PROJECT_ROOT / ".env").exists():
    load_dotenv(_PROJECT_ROOT / ".env.test")
