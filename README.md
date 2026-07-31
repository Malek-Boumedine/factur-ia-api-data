# factur-ia-api-data

## Docker / Déploiement

L'image de production est définie par le `Dockerfile` à la racine (multi-stage, `uv`, user non-root, aucun secret embarqué). Le `docker-compose.yml` reste réservé au développement local (il ne provisionne que MySQL).

### Construire l'image

```bash
docker build -t factur-ia-api .
```

Le build installe uniquement les dépendances de production (`uv sync --frozen--no-dev`). Les couches de dépendances sont mises en cache : un changement de code seul se reconstruit en quelques secondes.

### Lancer en local

Toute la configuration passe par les variables d'environnement (liste dans `.env.example` ; `SECRET_OCR_TOKEN` et `IBAN_ENCRYPTION_KEY` sont requises en plus). Aucun `.env` n'est copié dans l'image : le fournir à l'exécution.

```bash
docker run --rm -p 8080:8080 --env-file .env factur-ia-api
```

L'API écoute sur `$PORT` (8080 par défaut). Attention : depuis le conteneur, `DB_HOST=localhost` ne pointe pas vers le MySQL du compose — utiliser `host.docker.internal` (ou attacher le conteneur au réseau du compose).

### Migrations et seeds — jamais au démarrage du conteneur

Le conteneur ne lance **que** l'API. Les migrations et les seeds s'exécutent séparément, avec la même image (zéro dérive de version) :

```bash
docker run --rm --env-file .env factur-ia-api alembic upgrade head
docker run --rm --env-file .env factur-ia-api python -m src.core.seed
```

Pourquoi pas au démarrage : sur Cloud Run, plusieurs instances qui scalent migreraient en parallèle (course sur le schéma), le cold start s'allonge, et une migration qui échoue mettrait le service en crash-loop au lieu de faire échouer proprement le déploiement.

### Cloud Run

- **Port** : Cloud Run injecte `PORT` (8080 par défaut), le `CMD` de l'image l'utilise tel quel. Un seul worker uvicorn par conteneur : c'est Cloud Run qui scale horizontalement.
- **Probes** : pas de `HEALTHCHECK` Docker (Cloud Run l'ignore). Configurer les probes startup/liveness du service sur `GET /health`.
- **Migrations** : créer un **Cloud Run Job** avec la même image et la commande `alembic upgrade head`, à exécuter avant chaque déploiement du service (idem `python -m src.core.seed` pour les référentiels).

```bash
gcloud run jobs create factur-ia-migrate \
  --image <IMAGE> --command alembic --args upgrade,head
gcloud run jobs execute factur-ia-migrate --wait
```

### Limites connues (à traiter avant une vraie prod)

1. **`uploads/` est éphémère sur Cloud Run** : les documents uploadés sont écrits sur le disque local du conteneur (système de fichiers en mémoire), et **perdus au recyclage de l'instance**. À migrer vers un stockage objet (GCS) — tâche de production à part entière.
2. **`API_HOST` / `API_PORT` sont requises par `Settings`** (`src/core/config.py`) alors qu'uvicorn ne les lit pas dans le conteneur (il écoute sur `$PORT`). Les fournir quand même au runtime, sinon l'application refuse de démarrer.
3. **CORS** : `allow_origins=["*"]` dans `src/main.py` — à restreindre avant toute exposition publique.
