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
- **Probes** : pas de `HEALTHCHECK` Docker (Cloud Run l'ignore). Deux endpoints dédiés, publics, hors contrat OpenAPI et hors rate-limiting :
  - `GET /health` (**liveness**) : « le processus est-il vivant ? » — 200 inconditionnel, aucune I/O, aucune dépendance. Un échec provoque le **redémarrage** du conteneur ; c'est pourquoi cette sonde ne teste jamais la base (une panne MySQL ferait redémarrer toutes les instances en boucle).
  - `GET /ready` (**readiness**) : « le service peut-il traiter des requêtes ? » — `SELECT 1` sur MySQL avec timeout de 2 s. Répond **503** si la base est indisponible : l'instance est **retirée du trafic** sans être tuée, et se rétablit d'elle-même au retour de la base. Seule la base est testée : l'API IA (OCR) et Chorus Pro ne sont pas critiques (leur indisponibilité dégrade une fonctionnalité, pas le service).
  - Configuration suggérée : **startup probe** sur `/health` (`periodSeconds: 10`, `failureThreshold: 6`, `timeoutSeconds: 4` — laisse ~60 s de cold start) ; **liveness probe** sur `/health` (`periodSeconds: 30`, `timeoutSeconds: 4`, `failureThreshold: 3`). Cloud Run ne propose pas de readiness probe continue au sens Kubernetes ; `/ready` sert au monitoring (uptime check sur `/ready` = alerte « service hors trafic ») et de readiness si le service est déployé un jour sur GKE/Kubernetes.
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

## Observabilité (OpenTelemetry)

Traces distribuées des requêtes HTTP entrantes (FastAPI), des requêtes SQL (SQLAlchemy) et des appels sortants httpx (SIRENE, API IA, Chorus Pro). **Désactivé par défaut** : sans activation explicite, rien n'est instrumenté — local et CI inchangés. L'initialisation vit dans `src/core/telemetry.py`.

### Activer

```bash
OTEL_ENABLED="True"
OTEL_SERVICE_NAME="factur-ia-api"                      # nom du service dans les traces
OTEL_EXPORTER_OTLP_ENDPOINT="http://localhost:4318"    # collector OTLP/HTTP
# échantillonnage en production (optionnel, défaut : tout tracer) :
# OTEL_TRACES_SAMPLER="parentbased_traceidratio"
# OTEL_TRACES_SAMPLER_ARG="0.1"
```

Un collector injoignable ne fait jamais tomber l'API : l'export part d'un thread de fond et échoue en silence.

### Vérifier en local sans collector

```bash
OTEL_ENABLED=True OTEL_TRACES_EXPORTER=console uv run uvicorn src.main:app
```

Les spans s'impriment en JSON dans la console à chaque requête. Pour une visualisation complète, un Jaeger local suffit :

```bash
docker run --rm -p 16686:16686 -p 4318:4318 jaegertracing/all-in-one
# puis OTEL_ENABLED=True OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
# et l'UI sur http://localhost:16686
```

### Ce que les spans contiennent — et surtout pas

Capturé : méthode HTTP, route templatée (`/clients/{id_client}`, jamais l'identifiant réel), code de statut, durée, hôte et chemin des appels sortants, opération SQL avec placeholders, contexte de trace.

Jamais capturé (garanties posées dans `src/core/telemetry.py`) :

- **headers** (`Authorization`, `cpro-account`, `X-OCR-Secret-Token`, `x-entreprise-id`) : capture désactivée — ne jamais définir les variables `OTEL_INSTRUMENTATION_HTTP_CAPTURE_HEADERS_*` ;
- **corps de requête/réponse** (non supporté par les instrumentations utilisées) ;
- **paramètres SQL** : `db.statement` ne contient que la requête avec placeholders, jamais les valeurs liées (IBAN, emails…) ;
- **query strings d'URL** : retirées des spans par hooks de scrubbing (le client SIRENE appelle `/search?q=<SIRET>` — le SIRET ne fuit pas dans les traces).

`/health`, `/ready`, `/metrics` et `/` sont exclues du tracing (sondes Cloud Run et scrape Prometheus en continu : aucun intérêt, coût en volume).

## Métriques (Prometheus)

Les mêmes instrumentations OpenTelemetry produisent aussi des **métriques** (débit, latence, erreurs, appels sortants, pool DB), exposées au format Prometheus sur `GET /metrics` — sans Collector, via `PrometheusMetricReader`. Interrupteur séparé des traces : `OTEL_METRICS_ENABLED` (défaut `False`, rien ne change si désactivé). Les quatre combinaisons traces/métriques sont indépendantes.

**`/metrics` ne doit jamais être public en production** : ne pas activer `OTEL_METRICS_ENABLED` sur Cloud Run (les métriques y passeraient par un sidecar/Cloud Monitoring) ; si un jour c'est nécessaire, restreindre l'accès par ingress/IAM. C'est un outil de dev local.

Vérification rapide : lancer l'API avec `OTEL_METRICS_ENABLED=True uv run uvicorn src.main:app --reload`, puis `curl localhost:8000/metrics` doit répondre au format texte Prometheus.

Limites assumées : les labels sont templatés et à cardinalité bornée (`http_route="/clients/{id_client}"`, jamais d'ID réel ni de query string) ; la latence *par requête SQL* n'existe pas en métrique (l'instrumentation SQLAlchemy n'expose que le pool de connexions) — elle relève des traces.

### Stack de visualisation

Ce dépôt ne fait que **produire** les métriques. La stack qui les scrape et les visualise (Prometheus, Grafana, dashboard, règles d'alerte) vit dans le dépôt d'infrastructure [factur-ia-infra](https://github.com/Malek-Boumedine/factur-ia-infra) : une stack unifiée qui scrape les trois services du projet. On y trouve aussi les seuils d'alerte, leur raisonnement et les procédures de démonstration (Pending → Firing).

Couplage à connaître : le seuil de l'alerte « Pool DB — saturation » (12 connexions) est dérivé de la config SQLAlchemy de **ce** service (`pool_size` 5 + `max_overflow` 10 = 15, défauts non surchargés dans `core/database.py` ; 12 = 80 %). Modifier le pool ici impacte une règle définie dans `factur-ia-infra` — mettre les deux à jour ensemble.

Particularité à connaître : l'instrumentation httpx standard n'enregistre **aucune métrique quand la connexion échoue** (l'exception est relevée avant l'enregistrement de l'histogramme) — un service externe éteint serait invisible. Le compteur maison `external_api_unavailable_total` (label `service` : `sirene`, `ia_api`, `chorus_pro`) comble ce trou : il est incrémenté par les clients de `src/integrations/` sur chaque `httpx.RequestError` (connexion, DNS, timeout), là où l'échec est déjà loggé — et jamais sur une réponse 5xx, déjà comptée par l'instrumentation (pas de double comptage). C'est lui qui rend l'alerte « Dépendances externes » (définie dans `factur-ia-infra`) réellement utile.
