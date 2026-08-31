# syntax=docker/dockerfile:1
# Image de production de l'API (FastAPI, Python 3.13, uv).
#
# Multi-stage :
#   - build  : installation des dépendances de production avec uv, en deux couches (dépendances puis projet) pour profiter du cache Docker ;
#   - finale : python:3.13-slim sans uv, venv copié tel quel, user non-root.
#
# Aucun secret dans l'image : toute la configuration passe par les variables d'environnement à l'exécution (cf. .env.example et src/core/config.py). Les migrations ne sont JAMAIS lancées au démarrage du conteneur : elles se lancent via un job dédié utilisant cette même image — voir la section « Docker / Déploiement » du README.

# L'image uv officielle est basée sur python:3.13-slim-bookworm : même Python et même Debian que l'image finale, le venv se copie donc tel quel.
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS build

# Bytecode précompilé : image un peu plus lourde, cold start plus rapide.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Couche dépendances : réutilisée tant que pyproject.toml/uv.lock ne changent pas. Seules les dépendances de production sont installées (pas dev/test).
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# Couche projet : seule à être reconstruite quand le code change. README.md est requis par le build hatchling (`readme` déclaré dans pyproject.toml) ; installer le projet permet à get_app_version() de lire la vraie version.
COPY README.md ./
COPY src/ src/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev


FROM python:3.13-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN groupadd --system app && useradd --system --gid app --home /app app

COPY --from=build --chown=app:app /app/.venv .venv
COPY --chown=app:app src/ src/
# Migrations embarquées pour le job de déploiement (jamais exécutées au boot).
COPY --chown=app:app migrations/ migrations/
COPY --chown=app:app alembic.ini ./

# Stockage local des documents uploadés. Éphémère sur Cloud Run : les fichiers sont perdus au recyclage de l'instance — cf. limites dans le README.
RUN mkdir -p uploads/documents && chown -R app:app uploads

USER app

EXPOSE 8080

# Pas de HEALTHCHECK Docker : Cloud Run l'ignore et utilise ses propres probes HTTP (à pointer sur /health) — cf. README.
#
# `sh -c` + `exec` : expansion de $PORT (imposé par Cloud Run) tout en gardant uvicorn en PID 1 pour recevoir les signaux d'arrêt. Un seul worker : c'est Cloud Run qui scale horizontalement. --proxy-headers : derrière le proxy Cloud Run, sinon le rate-limiting (slowapi) verrait l'IP du proxy pour tous les clients.
CMD ["/bin/sh", "-c", "exec uvicorn src.main:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1 --proxy-headers --forwarded-allow-ips '*'"]
