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

## Métriques (Prometheus / Grafana)

Les mêmes instrumentations OpenTelemetry produisent aussi des **métriques** (débit, latence, erreurs, appels sortants, pool DB), exposées au format Prometheus sur `GET /metrics` — sans Collector, via `PrometheusMetricReader`. Interrupteur séparé des traces : `OTEL_METRICS_ENABLED` (défaut `False`, rien ne change si désactivé). Les quatre combinaisons traces/métriques sont indépendantes.

**`/metrics` ne doit jamais être public en production** : ne pas activer `OTEL_METRICS_ENABLED` sur Cloud Run (les métriques y passeraient par un sidecar/Cloud Monitoring) ; si un jour c'est nécessaire, restreindre l'accès par ingress/IAM. C'est un outil de dev local.

### Lancer la stack locale

```bash
# 1. l'API sur l'hôte, métriques activées :
OTEL_METRICS_ENABLED=True uv run uvicorn src.main:app --reload

# 2. Prometheus + Grafana (stack autonome, séparée du compose MySQL) :
docker compose -f docker-compose.observability.yml up -d
```

- **Grafana** : http://localhost:3000 — accès anonyme (dev), datasource Prometheus et dashboard « Factur-IA API » pré-provisionnés (`observability/grafana/`). Panneaux : débit par route, latence p50/p95/p99, taux d'erreur 4xx/5xx, requêtes en vol, débit et latence des appels sortants par hôte (SIRENE, API IA, Chorus Pro), pool de connexions DB.
- **Prometheus** : http://localhost:9090 — scrape l'API toutes les 15 s sur `host.docker.internal:8000` (config : `observability/prometheus/prometheus.yml` ; adapter le port si uvicorn n'écoute pas sur 8000).
- Vérification rapide sans Docker : `curl localhost:8000/metrics` doit répondre au format texte Prometheus.

Limites assumées : les labels sont templatés et à cardinalité bornée (`http_route="/clients/{id_client}"`, jamais d'ID réel ni de query string) ; la latence *par requête SQL* n'existe pas en métrique (l'instrumentation SQLAlchemy n'expose que le pool de connexions) — elle relève des traces.

### Alertes et seuils

Provisionnées dans Grafana (`observability/grafana/provisioning/alerting/alertes.yml`), sans Alertmanager : une brique de moins, et l'état Normal / Pending / Firing est visible directement dans **Alerting → Alert rules**. Chaque règle mesure sur une fenêtre de 5 min, est évaluée chaque minute, et ne passe en Firing que si la condition tient 2 min (`for:`) — un pic isolé d'une seule évaluation ne déclenche rien.

| Alerte | Seuil | Durée avant Firing | Sévérité |
| --- | --- | --- | --- |
| API — taux de 5xx élevé | > 5 % des réponses sur 5 min | 2 min | warning |
| API — latence p95 dégradée | > 2 s sur 5 min | 2 min | warning |
| Dépendances externes — appels en erreur (5xx + échecs de connexion) | > 20 % des appels sortants sur 5 min | 2 min | critical |
| Pool DB — saturation | > 12 connexions utilisées (80 % de la capacité) | 2 min | warning |
| API hors ligne | cible Prometheus down | 2 min | critical |

Raisonnement des seuils :

- **5 % de 5xx** : en régime normal le taux est ~0 ; 5 % ne se franchit pas par accident dès qu'il y a du trafic, mais une panne réelle (base coupée) donne ~100 %.
- **p95 > 2 s** : une API CRUD répond en dizaines de ms ; 2 s est une dégradation indiscutable, avec une marge énorme contre les fausses alertes. Pas de démo dédiée, mais elle se déclenche dès qu'un incident ralentit réellement les réponses : observée en Firing pendant la démo « Pool DB » (les requêtes bloquées par le verrou finissent avec des durées de plusieurs dizaines de secondes), et une dépendance qui timeoute suffit aussi (l'appel SIRENE entrant attend jusqu'à 5 s).
- **20 % d'appels sortants en échec** : tolère les échecs ponctuels et les rejeux ; une dépendance éteinte fait tendre le ratio de son trafic vers 100 %.
- **Pool DB > 12** : capacité = `pool_size` 5 + `max_overflow` 10 = 15 (défauts SQLAlchemy, non surchargés dans `core/database.py`) ; 12 = 80 %, le signal avant que les requêtes n'attendent une connexion.
- **API hors ligne** : `up{job="factur-ia-api"} < 1`, binaire, rien à régler. Seule règle en `noDataState: Alerting` (l'absence de donnée est le symptôme) ; les autres restent en `OK` (pas de trafic ≠ panne).

Particularité à connaître : l'instrumentation httpx standard n'enregistre **aucune métrique quand la connexion échoue** (l'exception est relevée avant l'enregistrement de l'histogramme) — un service externe éteint serait invisible. Le compteur maison `external_api_unavailable_total` (label `service` : `sirene`, `ia_api`, `chorus_pro`) comble ce trou : il est incrémenté par les clients de `src/integrations/` sur chaque `httpx.RequestError` (connexion, DNS, timeout), là où l'échec est déjà loggé — et jamais sur une réponse 5xx, déjà comptée par l'instrumentation (pas de double comptage). C'est lui qui rend l'alerte « Dépendances externes » réellement utile.

### Rejouer la démonstration (Pending → Firing)

Démo de l'alerte « Dépendances externes » (déterministe, ~3 min) :

```bash
# 1. Stack d'observabilité + MySQL démarrés, puis l'API avec l'API IA
#    pointée sur un port fermé (simule une API IA éteinte) :
IA_API_BASE_URL=http://localhost:9999 OTEL_METRICS_ENABLED=True \
  uv run uvicorn src.main:app

# 2. Générer du trafic sortant : uploader plusieurs fois un document
#    (chaque upload tente le déclenchement OCR → échec de connexion compté).
#    Répéter ~1 fois toutes les 10-15 s pendant 3 min.

# 3. Observer : Grafana → Alerting → Alert rules →
#    « Dépendances externes — appels en erreur » passe Normal → Pending →
#    Firing (~3 min). Le panel « Appels sortants — échecs de connexion »
#    du dashboard montre la dépendance en cause (label service).
```

Autres démonstrations : arrêter uvicorn → « API hors ligne » en Firing en ~2-3 min (et retour Normal au redémarrage) ; couper MySQL (`docker compose stop db`) en générant du trafic → « API — taux de 5xx élevé ».

Pour « Pool DB — saturation », une charge de requêtes *rapides* ne suffit pas (les connexions sont rendues en quelques ms, la jauge `state="used"` reste ~0 au moment du scrape) : il faut des requêtes qui **retiennent** les connexions — le vrai scénario visé par l'alerte. Démonstration reproductible : poser un verrou exclusif (`docker exec factur_ia_db_container mysql -u… -p… factur_ia_db -e "LOCK TABLES facture WRITE; DO SLEEP(300); UNLOCK TABLES;"`) pendant une charge concurrente (~40 clients sur `/factures/`) → les SELECT s'empilent, `used` monte à 15/15 en quelques secondes, Firing en ~3 min, retour à Normal au déverrouillage.
