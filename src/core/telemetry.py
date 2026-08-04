"""Instrumentation OpenTelemetry : traces distribuées et métriques.

Deux interrupteurs indépendants, tous deux désactivés par défaut — si aucun
n'est actif, ``setup_telemetry`` ne fait rien (ni import du SDK ni
instrumentation), aucun changement de comportement en local ou en CI :

- ``OTEL_ENABLED`` : **traces** des requêtes HTTP entrantes (FastAPI), des
  requêtes SQL (SQLAlchemy) et des appels httpx sortants (SIRENE, API IA,
  Chorus Pro), exportées en OTLP/HTTP vers ``OTEL_EXPORTER_OTLP_ENDPOINT``.
  Un collector injoignable ne fait jamais tomber l'API : l'export part d'un
  thread de fond et échoue en silence.
- ``OTEL_METRICS_ENABLED`` : **métriques** des mêmes instrumentations
  (histogrammes de durée HTTP entrant/sortant, requêtes en vol, pool de
  connexions DB), exposées au format Prometheus sur ``/metrics`` — scrapé par
  la stack locale ``docker-compose.observability.yml``. En production,
  ``/metrics`` ne doit pas être public : ne pas activer sur Cloud Run.

Les conventions sémantiques HTTP *stables* sont adoptées via la variable
standard ``OTEL_SEMCONV_STABILITY_OPT_IN=http`` (surchargeable par
l'environnement) : sans elles, l'histogramme HTTP n'a pas de label
``http.route`` et aucun découpage par route n'est possible.

Garanties sur les données sensibles — aucun secret ni donnée
personnelle/bancaire ne part dans les spans ni dans les métriques :

- **headers jamais capturés** (comportement par défaut des instrumentations ;
  ne jamais définir les variables ``OTEL_INSTRUMENTATION_HTTP_CAPTURE_HEADERS_*``) :
  ``Authorization`` (JWT, Bearer PISTE), ``cpro-account``,
  ``X-OCR-Secret-Token`` et ``x-entreprise-id`` restent hors traces ;
- **corps de requête/réponse jamais capturés** (non supporté par ces
  instrumentations) ;
- **paramètres SQL jamais capturés** : ``db.statement`` ne contient que la
  requête avec placeholders, jamais les valeurs liées (IBAN, emails…) ;
- **query strings retirées des URLs** par les hooks ci-dessous : le client
  SIRENE appelle ``/search?q=<SIRET>``, la query ne doit pas fuiter. Les spans
  ne gardent que schéma + hôte + chemin ;
- **labels de métriques à cardinalité bornée, sans ID réel** : route
  templatée (``/clients/{id_client}``), méthode, code de statut côté serveur ;
  hôte et port de destination côté client (jamais le chemin ni la query).

Sont capturés, et rien d'autre : méthode HTTP, route templatée, code de
statut, durée, hôte et chemin des appels sortants, opération SQL avec
placeholders, nom du service, contexte de trace.
"""

import logging
import os
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import urlsplit, urlunsplit

from fastapi import FastAPI

from src.core.config import settings

if TYPE_CHECKING:
    from opentelemetry.metrics import Counter
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.trace import Span

# Les trois dépendances externes de l'API, seules valeurs admises du label
# `service` du compteur d'indisponibilité : cardinalité bornée, aucun ID réel.
ExternalService = Literal["sirene", "ia_api", "chorus_pro"]

# Compteur des échecs de connexion aux services externes, créé par
# `_build_meter_provider` quand les métriques sont activées ; sinon None et
# `record_external_api_unavailable` ne fait rien.
_external_api_unavailable_counter: "Counter | None" = None

# Sondes Cloud Run appelées en continu (/health, /ready), page d'accueil et
# endpoint Prometheus (/metrics, scrapé toutes les 15 s) : aucune valeur
# d'observabilité, exclus du tracing ET des métriques (l'exclusion ASGI coupe
# les deux avant tout enregistrement). Regex cherchées (re.search) dans
# « scheme://host/chemin » — sans query string.
EXCLUDED_URLS = r"/health$,/ready$,/metrics$,^https?://[^/]+/$"

# Variables standard OpenTelemetry relayées vers os.environ : le SDK et les
# instrumentations ne lisent pas le .env (chargé par pydantic-settings sans
# export dans l'environnement).
_OTEL_ENV_VARS = (
    "OTEL_SERVICE_NAME",
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "OTEL_TRACES_EXPORTER",
    "OTEL_TRACES_SAMPLER",
    "OTEL_TRACES_SAMPLER_ARG",
    "OTEL_SEMCONV_STABILITY_OPT_IN",
)


def scrub_url(url: object) -> str:
    """Réduit une URL à « schéma://hôte/chemin » : sans credentials, query ni
    fragment."""
    parts = urlsplit(str(url))
    netloc = parts.netloc.rpartition("@")[2]
    return urlunsplit((parts.scheme, netloc, parts.path, "", ""))


def scrub_span_url_attributes(span: "Span") -> None:
    """Écrase les attributs d'URL d'un span par leur version sans query string.

    Couvre les deux générations de conventions sémantiques HTTP : ``http.url``
    (anciennes) et ``url.full`` / ``url.query`` (stables, activées par
    ``OTEL_SEMCONV_STABILITY_OPT_IN=http``).
    """
    attributes = getattr(span, "attributes", None) or {}
    for key in ("http.url", "url.full"):
        value = attributes.get(key)
        if value is not None:
            span.set_attribute(key, scrub_url(value))
    if "url.query" in attributes:
        span.set_attribute("url.query", "")


def record_external_api_unavailable(service: ExternalService) -> None:
    """Compte un échec de connexion (réseau, DNS, timeout) à un service externe.

    À appeler uniquement sur ``httpx.RequestError`` : les réponses 5xx sont
    déjà enregistrées par l'instrumentation httpx, les compter ici les
    compterait double. Nécessaire car l'instrumentation httpx n'enregistre
    AUCUNE métrique quand la connexion échoue (l'exception est relevée avant
    l'enregistrement de l'histogramme) : sans ce compteur, une dépendance
    éteinte serait invisible dans les métriques et les alertes. No-op si les
    métriques sont désactivées.
    """
    if _external_api_unavailable_counter is not None:
        _external_api_unavailable_counter.add(1, {"service": service})


def _server_request_hook(span: "Span", scope: dict[str, Any]) -> None:
    """Hook FastAPI/ASGI : scrubbing d'URL des spans serveur."""
    scrub_span_url_attributes(span)


def _client_request_hook(span: "Span", request_info: Any) -> None:
    """Hook httpx (clients sync) : scrubbing d'URL des spans sortants."""
    scrub_span_url_attributes(span)


async def _async_client_request_hook(span: "Span", request_info: Any) -> None:
    """Hook httpx (clients async) : scrubbing d'URL des spans sortants."""
    scrub_span_url_attributes(span)


def _build_tracer_provider() -> "TracerProvider":
    """Construit le pipeline de traces : provider + export OTLP ou console."""
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import (
        BatchSpanProcessor,
        ConsoleSpanExporter,
        SpanExporter,
    )

    # Un collector absent ou injoignable ne doit ni faire tomber l'API ni
    # remplir les logs : les échecs d'export sont réduits au silence.
    # L'activation se vérifie avec OTEL_TRACES_EXPORTER=console.
    for noisy_logger in (
        "opentelemetry.exporter.otlp.proto.http.trace_exporter",
        "opentelemetry.sdk.trace.export",
    ):
        logging.getLogger(noisy_logger).setLevel(logging.CRITICAL)

    exporter: SpanExporter
    if settings.OTEL_TRACES_EXPORTER == "console":
        exporter = ConsoleSpanExporter()
    else:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )

        # Endpoint lu depuis OTEL_EXPORTER_OTLP_ENDPOINT (défaut : localhost:4318).
        exporter = OTLPSpanExporter()

    # Le sampler est construit depuis OTEL_TRACES_SAMPLER / _ARG (défaut :
    # parentbased_always_on).
    provider = TracerProvider(
        resource=Resource.create({"service.name": settings.OTEL_SERVICE_NAME})
    )
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    return provider


def _build_meter_provider(app: FastAPI) -> "MeterProvider":
    """Construit le pipeline de métriques et monte ``/metrics`` sur l'app.

    Le ``PrometheusMetricReader`` expose les métriques OTel au format
    Prometheus (mode pull, aucun collector requis) dans un registre dédié —
    jamais le registre global de ``prometheus_client``, pour rester sans
    effet de bord. La route est hors contrat OpenAPI et hors rate-limiting.
    """
    from fastapi import Response
    from opentelemetry.exporter.prometheus import PrometheusMetricReader
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.resources import Resource
    from prometheus_client import (
        CONTENT_TYPE_LATEST,
        CollectorRegistry,
        generate_latest,
    )

    global _external_api_unavailable_counter

    registry = CollectorRegistry()
    reader = PrometheusMetricReader(registry=registry)
    provider = MeterProvider(
        resource=Resource.create({"service.name": settings.OTEL_SERVICE_NAME}),
        metric_readers=[reader],
    )

    # Exposé côté Prometheus sous le nom `external_api_unavailable_total`.
    meter = provider.get_meter("src.core.telemetry")
    _external_api_unavailable_counter = meter.create_counter(
        "external_api.unavailable",
        unit="1",
        description=(
            "Échecs de connexion aux services externes (SIRENE, API IA, Chorus Pro)"
        ),
    )

    def metrics_endpoint() -> Response:
        """Expose le registre au format texte Prometheus."""
        return Response(generate_latest(registry), media_type=CONTENT_TYPE_LATEST)

    app.add_api_route(
        "/metrics", metrics_endpoint, methods=["GET"], include_in_schema=False
    )
    return provider


def setup_telemetry(app: FastAPI) -> None:
    """Active traces et/ou métriques sur l'app, ou ne fait rien si tout est
    désactivé.

    Les instrumentations sont posées une seule fois et partagées par les deux
    pipelines ; la brique non activée reçoit un provider no-op explicite
    (jamais le provider global, pour rester déterministe).
    """
    if not (settings.OTEL_ENABLED or settings.OTEL_METRICS_ENABLED):
        return

    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
    from opentelemetry.metrics import NoOpMeterProvider
    from opentelemetry.trace import NoOpTracerProvider

    from src.core.database import engine

    # Relais des variables standard avant toute initialisation des
    # instrumentations (le opt-in semconv est lu une seule fois, au premier
    # instrument) ; l'environnement réel reste prioritaire (setdefault).
    for name in _OTEL_ENV_VARS:
        value = getattr(settings, name)
        if value is not None:
            os.environ.setdefault(name, str(value))

    tracer_provider = (
        _build_tracer_provider() if settings.OTEL_ENABLED else NoOpTracerProvider()
    )
    meter_provider = (
        _build_meter_provider(app)
        if settings.OTEL_METRICS_ENABLED
        else NoOpMeterProvider()
    )

    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        excluded_urls=EXCLUDED_URLS,
        server_request_hook=_server_request_hook,
    )
    # L'engine async expose son moteur synchrone sous-jacent, seul point
    # d'accroche des événements SQLAlchemy. enable_commenter reste désactivé :
    # pas d'enrichissement du SQL émis.
    SQLAlchemyInstrumentor().instrument(
        engine=engine.sync_engine,
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        enable_commenter=False,
    )
    # Instrumentation globale : couvre les AsyncClient créés à la volée dans
    # les trois clients sortants, y compris avec un transport injecté.
    HTTPXClientInstrumentor().instrument(
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        request_hook=_client_request_hook,
        async_request_hook=_async_client_request_hook,
    )
