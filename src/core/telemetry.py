"""Instrumentation OpenTelemetry (traces distribuées).

Désactivée par défaut : si ``OTEL_ENABLED`` est faux, ``setup_telemetry`` ne
fait rien — ni import du SDK ni instrumentation, aucun changement de
comportement en local ou en CI. Activée, elle trace les requêtes HTTP
entrantes (FastAPI), les requêtes SQL (SQLAlchemy) et les appels httpx
sortants (SIRENE, API IA, Chorus Pro), exportés en OTLP/HTTP vers
``OTEL_EXPORTER_OTLP_ENDPOINT``. Un collector injoignable ne fait jamais
tomber l'API : l'export part d'un thread de fond et échoue en silence.

Garanties sur les données sensibles — aucun secret ni donnée
personnelle/bancaire ne part dans les spans :

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
  ne gardent que schéma + hôte + chemin.

Sont capturés, et rien d'autre : méthode HTTP, route templatée
(``/clients/{id_client}``), code de statut, durée, hôte et chemin des appels
sortants, opération SQL avec placeholders, nom du service, contexte de trace.
"""

import logging
import os
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit, urlunsplit

from fastapi import FastAPI

from src.core.config import settings

if TYPE_CHECKING:
    from opentelemetry.trace import Span

# Sondes Cloud Run appelées en continu (/health, /ready) et page d'accueil :
# aucune valeur d'observabilité, exclues du tracing. Regex cherchées
# (re.search) dans « scheme://host/chemin » — sans query string.
EXCLUDED_URLS = r"/health$,/ready$,^https?://[^/]+/$"

# Variables standard OpenTelemetry relayées vers os.environ : le SDK ne lit
# pas le .env (chargé par pydantic-settings sans export dans l'environnement).
_OTEL_ENV_VARS = (
    "OTEL_SERVICE_NAME",
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "OTEL_TRACES_EXPORTER",
    "OTEL_TRACES_SAMPLER",
    "OTEL_TRACES_SAMPLER_ARG",
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
    (anciennes, par défaut) et ``url.full`` / ``url.query`` (nouvelles, si
    ``OTEL_SEMCONV_STABILITY_OPT_IN`` est activée un jour).
    """
    attributes = getattr(span, "attributes", None) or {}
    for key in ("http.url", "url.full"):
        value = attributes.get(key)
        if value is not None:
            span.set_attribute(key, scrub_url(value))
    if "url.query" in attributes:
        span.set_attribute("url.query", "")


def _server_request_hook(span: "Span", scope: dict[str, Any]) -> None:
    """Hook FastAPI/ASGI : scrubbing d'URL des spans serveur."""
    scrub_span_url_attributes(span)


def _client_request_hook(span: "Span", request_info: Any) -> None:
    """Hook httpx (clients sync) : scrubbing d'URL des spans sortants."""
    scrub_span_url_attributes(span)


async def _async_client_request_hook(span: "Span", request_info: Any) -> None:
    """Hook httpx (clients async) : scrubbing d'URL des spans sortants."""
    scrub_span_url_attributes(span)


def setup_telemetry(app: FastAPI) -> None:
    """Active le tracing OpenTelemetry sur l'app, ou ne fait rien si désactivé."""
    if not settings.OTEL_ENABLED:
        return

    from opentelemetry import trace
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import (
        BatchSpanProcessor,
        ConsoleSpanExporter,
        SpanExporter,
    )

    from src.core.database import engine

    # Un collector absent ou injoignable ne doit ni faire tomber l'API ni
    # remplir les logs : les échecs d'export sont réduits au silence.
    # L'activation se vérifie avec OTEL_TRACES_EXPORTER=console.
    for noisy_logger in (
        "opentelemetry.exporter.otlp.proto.http.trace_exporter",
        "opentelemetry.sdk.trace.export",
    ):
        logging.getLogger(noisy_logger).setLevel(logging.CRITICAL)

    for name in _OTEL_ENV_VARS:
        value = getattr(settings, name)
        if value is not None:
            os.environ.setdefault(name, str(value))

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

    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=provider,
        excluded_urls=EXCLUDED_URLS,
        server_request_hook=_server_request_hook,
    )
    # L'engine async expose son moteur synchrone sous-jacent, seul point
    # d'accroche des événements SQLAlchemy. enable_commenter reste désactivé :
    # pas d'enrichissement du SQL émis.
    SQLAlchemyInstrumentor().instrument(
        engine=engine.sync_engine,
        tracer_provider=provider,
        enable_commenter=False,
    )
    # Instrumentation globale : couvre les AsyncClient créés à la volée dans
    # les trois clients sortants, y compris avec un transport injecté.
    HTTPXClientInstrumentor().instrument(
        tracer_provider=provider,
        request_hook=_client_request_hook,
        async_request_hook=_async_client_request_hook,
    )
