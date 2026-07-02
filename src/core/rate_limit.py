"""
Limiteur de débit partagé (slowapi).

Défini dans un module dédié pour être importé à la fois par `src.main`
(câblage du handler et de l'état applicatif) et par les routers qui décorent
leurs endpoints avec `@limiter.limit(...)`, sans créer d'import circulaire.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

# Clé de limitation basée sur l'adresse IP du client.
limiter = Limiter(key_func=get_remote_address)
