# factur-ia-api-data

Service central de **Factur-IA**, solution de dématérialisation de factures. Il porte les données métier, les règles de gestion, et orchestre les intégrations : extraction automatique par le service d'IA, recherche d'entreprises au référentiel public, transmission des factures à l'administration.

Application **FastAPI / Python 3.13**, exposant environ **soixante-quinze points de terminaison** documentés au standard OpenAPI.

## Architecture

| Service | Rôle | Dépôt |
|---|---|---|
| Client web | Interface utilisateur | `factur-ia-web-client` |
| **API data** (ce dépôt) | Données métier, règles de gestion, intégrations | `factur-ia-api-data` |
| API IA | Extraction et structuration des documents | `factur-ia-api-ia` |

Ce service est le **seul point d'entrée aux données** : personne ne parle à la base ni aux services externes en dehors de lui.

## Installation

```bash
git clone https://github.com/Malek-Boumedine/factur-ia-api-data.git
cd factur-ia-api-data

uv sync --all-groups          # dépendances, groupes de dev inclus
cp .env.example .env          # puis renseigner les variables ci-dessous
docker compose up -d          # MySQL en local
```

**Prérequis** : Python 3.13, [uv](https://docs.astral.sh/uv/), Docker.

### Les secrets à générer

Quatre valeurs sont requises, sans quoi l'application ne démarre pas :

```bash
openssl rand -hex 32    # SECRET_KEY — signature des jetons applicatifs
openssl rand -hex 32    # SECRET_OCR_TOKEN — partagé avec l'API IA, même valeur des deux côtés
```

```bash
# IBAN_ENCRYPTION_KEY — clé de chiffrement des coordonnées bancaires
uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

**La clé de chiffrement est irremplaçable** : la perdre rend les coordonnées bancaires définitivement illisibles. La sauvegarder hors du projet.

La clé du fournisseur de modèle et les identifiants du portail de transmission viennent de leurs consoles respectives.

### Préparer la base

```bash
uv run alembic upgrade head       # schéma
uv run python -m src.core.seed    # données de référence et compte administrateur
```

Le peuplement crée les rôles et leurs permissions, les statuts de facture, les taux de TVA et les plans d'abonnement. Il est **idempotent** : relançable sans dommage.

## Lancement

```bash
uv run uvicorn src.main:app --reload --port 8080
```

Documentation interactive sur <http://localhost:8080/docs>.

### Vérifications

```bash
uv run pytest --cov=src            # tests
uv run mypy src/                   # typage strict
uv run pre-commit run --all-files  # lint et formatage
```

## Image de production

```bash
docker build -t factur-ia-api-data .
docker run --rm -p 8080:8080 --env-file .env factur-ia-api-data
```

Image multi-étapes, utilisateur non-root, aucun secret embarqué — la configuration est fournie à l'exécution. Le service écoute sur `$PORT`, injecté par la plateforme.

**Depuis le conteneur**, `DB_HOST=localhost` ne pointe pas vers le MySQL du compose : utiliser `host.docker.internal`.

### Migrations et peuplement : jamais au démarrage

Le conteneur ne lance **que** l'API. Les migrations et le peuplement s'exécutent séparément, avec la même image :

```bash
docker run --rm --env-file .env factur-ia-api-data alembic upgrade head
docker run --rm --env-file .env factur-ia-api-data python -m src.core.seed
```

**Pourquoi** : plusieurs instances qui démarrent en même temps migreraient en parallèle, avec une course sur le schéma. Et une migration qui échoue mettrait le service en boucle de redémarrage au lieu de faire échouer proprement le déploiement.

## Sondes de disponibilité

Deux routes destinées à la plateforme : publiques, hors contrat OpenAPI, sans information exploitable.

| Route | Rôle | Vérifie | Échec |
|---|---|---|---|
| `GET /health` | Le processus est-il vivant ? | rien | **Redémarrage** du conteneur |
| `GET /ready` | Le service peut-il travailler ? | Base joignable, avec délai de 2 s | **Retrait du trafic**, sans redémarrage |

`/health` répond 200 inconditionnellement : son échec redémarrant le conteneur, la faire dépendre de la base ferait redémarrer toutes les instances en boucle lors d'une panne.

`/ready` ne teste **que la base**. Le service d'extraction et le portail de transmission ne sont pas critiques : leur indisponibilité dégrade une fonctionnalité, pas le service.

## Livraison continue

À la publication d'une version, le workflow récupère le tag correspondant, construit l'image avec deux étiquettes — version et empreinte du commit, pas de `latest` —, la pousse, exécute le job de migration, déploie la révision par empreinte, puis interroge la sonde de santé avec un jeton d'identité. Un déclenchement manuel permet de redéployer n'importe quelle version.

**Partage des responsabilités** : l'infrastructure possède la *forme* du service — configuration, secrets, dimensionnement — et ignore le champ image ; la livraison possède son *contenu*.

**Contrainte sur les migrations** : elles s'exécutent avant la bascule, donc l'ancien code tourne brièvement sur le nouveau schéma. Elles doivent rester **rétro-compatibles d'une version** — pas de suppression ni de renommage de colonne encore utilisée.

### Variables GitHub

Aucun secret : la fédération d'identité rend tout stockage confidentiel inutile. Tout va dans les **variables de dépôt**.

| Variable | Contenu |
|---|---|
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | Fournisseur d'identité, sortie Terraform |
| `GCP_DEPLOY_SA` | `github-deployer-api-data@<projet>.iam.gserviceaccount.com` |
| `GCP_PROJECT_ID` | Identifiant du projet |
| `GCP_REGION` | `europe-west9` |
| `ARTIFACT_REGISTRY_REPO` | `factur-ia` |
| `CLOUD_RUN_SERVICE` | `factur-ia-api-data` |
| `CLOUD_RUN_MIGRATE_JOB` | `factur-ia-migrate-api-data` |

Les ressources correspondantes — compte de déploiement, rôles, liaison d'identité — sont décrites dans le dépôt [`factur-ia-infra`](https://github.com/Malek-Boumedine/factur-ia-infra).

## Sécurité et données personnelles

**Authentification** par jeton, avec mots de passe hachés à sel unique et liens de réinitialisation à usage unique stockés sous forme d'empreinte.

**Cloisonnement par entreprise** : toutes les tables métier portent l'identifiant du locataire, et l'appartenance est vérifiée à chaque requête — jamais seulement à l'entrée.

**Chiffrement au repos** des coordonnées bancaires. L'application refuse de démarrer sans sa clé, ce qui évite un fonctionnement dégradé silencieux. L'identifiant bancaire n'est jamais renvoyé en entier à l'interface, et il est masqué **avant enregistrement** lorsqu'il provient d'une extraction.

**Immuabilité comptable** : une facture validée conserve une copie figée des coordonnées de son client et ne peut plus être modifiée.

La [documentation de conformité](https://github.com/Malek-Boumedine/factur-ia-meta/tree/main/docs/rgpd) — registre des traitements, procédures de purge, mesures de sécurité — vit dans le dépôt de documentation.

## Observabilité

Le service est instrumenté avec OpenTelemetry : requêtes entrantes, requêtes SQL, et appels sortants vers les services externes. **Tout est désactivé par défaut** — deux interrupteurs indépendants, `OTEL_ENABLED` pour les traces et `OTEL_METRICS_ENABLED` pour les métriques.

Un collecteur injoignable ne fait jamais tomber l'API : l'export part d'un fil d'exécution de fond et échoue en silence.

### Ce que la télémétrie contient — et surtout pas

**Capturé** : méthode, route modélisée (jamais l'identifiant réel), statut, durée, opération SQL avec emplacements.

**Jamais capturé** : les en-têtes d'authentification, les corps de requête, les valeurs liées aux requêtes SQL, et les paramètres d'URL — une recherche d'entreprise en porte un identifiant.

Les sondes et la route des métriques sont exclues du traçage : interrogées en continu, elles écraseraient les statistiques du trafic réel.

### Un trou comblé

L'instrumentation HTTP standard n'enregistre **aucune métrique quand la connexion échoue** — un service externe éteint serait invisible. Un compteur maison le comble, incrémenté sur chaque erreur de transport et jamais sur une réponse en erreur du serveur, déjà comptée par ailleurs.

### Stack de visualisation

Ce dépôt ne fait que **produire** les métriques. La stack qui les collecte et les visualise vit dans [`factur-ia-infra`](https://github.com/Malek-Boumedine/factur-ia-infra), avec les seuils d'alerte et leur justification.

**Couplage à connaître** : le seuil de l'alerte sur le pool de connexions est dérivé de la configuration de **ce** service — 80 % de la capacité configurée. Modifier le pool ici impose de mettre à jour la règle là-bas.
