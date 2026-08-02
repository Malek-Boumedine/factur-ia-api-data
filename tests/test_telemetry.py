"""Tests de l'instrumentation OpenTelemetry (`src/core/telemetry.py`).

Aucun collector requis : la désactivation doit être transparente, et le
scrubbing des données sensibles est vérifié sur de vrais spans SDK gardés en
mémoire (jamais exportés).
"""

from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from opentelemetry.trace import Span
from opentelemetry.util.http import parse_excluded_urls
from src.core.config import settings
from src.core.telemetry import (
    EXCLUDED_URLS,
    _async_client_request_hook,
    _client_request_hook,
    _server_request_hook,
    scrub_span_url_attributes,
    scrub_url,
    setup_telemetry,
)


def make_recorded_span(
    attributes: dict[str, Any],
) -> tuple[Span, InMemorySpanExporter]:
    """Crée un span SDK réel (exporté en mémoire) portant les attributs donnés."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer(__name__)
    span = tracer.start_span("GET", attributes=attributes)
    return span, exporter


class TestSetupTelemetryDesactive:
    """Tout désactivé (défaut), l'instrumentation doit être invisible."""

    def test_aucun_middleware_ajoute(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "OTEL_ENABLED", False)
        monkeypatch.setattr(settings, "OTEL_METRICS_ENABLED", False)
        app = FastAPI()
        middlewares_avant = list(app.user_middleware)

        setup_telemetry(app)

        assert app.user_middleware == middlewares_avant
        assert not hasattr(app, "_original_build_middleware_stack")

    def test_app_non_marquee_instrumentee(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "OTEL_ENABLED", False)
        monkeypatch.setattr(settings, "OTEL_METRICS_ENABLED", False)
        app = FastAPI()

        setup_telemetry(app)

        assert not getattr(app, "_is_instrumented_by_opentelemetry", False)

    def test_aucune_route_metrics(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "OTEL_ENABLED", False)
        monkeypatch.setattr(settings, "OTEL_METRICS_ENABLED", False)
        app = FastAPI()

        setup_telemetry(app)

        assert all(getattr(r, "path", None) != "/metrics" for r in app.routes)


class TestScrubUrl:
    """La query string, les credentials et le fragment sont retirés."""

    @pytest.mark.parametrize(
        ("url", "attendu"),
        [
            # Le cas critique : le SIRET passé en query par le client SIRENE.
            (
                "https://recherche-entreprises.api.gouv.fr/search?q=13002526500013",
                "https://recherche-entreprises.api.gouv.fr/search",
            ),
            (
                # pragma: allowlist nextline secret
                "http://user:secret@localhost:8001/extractions?a=1#frag",
                "http://localhost:8001/extractions",
            ),
            # URL déjà propre : inchangée.
            (
                "https://sandbox-api.piste.gouv.fr/cpro/factures/v1/deposer/flux",
                "https://sandbox-api.piste.gouv.fr/cpro/factures/v1/deposer/flux",
            ),
        ],
    )
    def test_scrubbing(self, url: str, attendu: str) -> None:
        assert scrub_url(url) == attendu


class TestScrubSpanUrlAttributes:
    """Le scrubbing agit sur de vrais spans, pour les deux générations de
    conventions sémantiques HTTP."""

    def test_anciennes_conventions_http_url(self) -> None:
        span, exporter = make_recorded_span(
            {"http.url": "https://api.gouv.fr/search?q=13002526500013"}
        )
        scrub_span_url_attributes(span)
        span.end()

        (fini,) = exporter.get_finished_spans()
        assert fini.attributes is not None
        assert fini.attributes["http.url"] == "https://api.gouv.fr/search"
        assert "13002526500013" not in str(fini.attributes)

    def test_nouvelles_conventions_url_full_et_query(self) -> None:
        span, exporter = make_recorded_span(
            {
                "url.full": "https://api.gouv.fr/search?q=13002526500013",
                "url.query": "q=13002526500013",
            }
        )
        scrub_span_url_attributes(span)
        span.end()

        (fini,) = exporter.get_finished_spans()
        assert fini.attributes is not None
        assert fini.attributes["url.full"] == "https://api.gouv.fr/search"
        assert fini.attributes["url.query"] == ""
        assert "13002526500013" not in str(fini.attributes)

    def test_span_sans_attribut_url_inchange(self) -> None:
        span, exporter = make_recorded_span({"http.method": "GET"})
        scrub_span_url_attributes(span)
        span.end()

        (fini,) = exporter.get_finished_spans()
        assert fini.attributes is not None
        assert dict(fini.attributes) == {"http.method": "GET"}


class TestHooks:
    """Les hooks branchés sur les instrumentations délèguent au scrubbing."""

    def test_hook_serveur(self) -> None:
        span, exporter = make_recorded_span({"http.url": "http://api/clients?page=2"})
        _server_request_hook(span, {"type": "http"})
        span.end()

        (fini,) = exporter.get_finished_spans()
        assert fini.attributes is not None
        assert fini.attributes["http.url"] == "http://api/clients"

    def test_hook_client_sync(self) -> None:
        span, exporter = make_recorded_span({"http.url": "http://api/search?q=x"})
        _client_request_hook(span, None)
        span.end()

        (fini,) = exporter.get_finished_spans()
        assert fini.attributes is not None
        assert fini.attributes["http.url"] == "http://api/search"

    async def test_hook_client_async(self) -> None:
        span, exporter = make_recorded_span({"http.url": "http://api/search?q=x"})
        await _async_client_request_hook(span, None)
        span.end()

        (fini,) = exporter.get_finished_spans()
        assert fini.attributes is not None
        assert fini.attributes["http.url"] == "http://api/search"


class TestUrlsExclues:
    """/health, /ready, /metrics et la racine sont hors tracing ; les routes
    métier non.

    Les URLs testées reproduisent le format vu par le middleware ASGI :
    « scheme://host/chemin », sans query string.
    """

    @pytest.mark.parametrize(
        "url",
        [
            "http://testserver/health",
            "http://testserver/ready",
            "http://testserver/metrics",
            "http://testserver/",
            "https://api.factur-ia.fr/",
        ],
    )
    def test_exclues(self, url: str) -> None:
        assert parse_excluded_urls(EXCLUDED_URLS).url_disabled(url)

    @pytest.mark.parametrize(
        "url",
        [
            "http://testserver/clients",
            "http://testserver/factures/12",
            "http://testserver/healthcheck",
            "http://testserver/ready-set-go",
            "http://testserver/metrics-export",
        ],
    )
    def test_non_exclues(self, url: str) -> None:
        assert not parse_excluded_urls(EXCLUDED_URLS).url_disabled(url)


class TestSetupTelemetryActive:
    """Activée, l'instrumentation s'accroche bien à l'app FastAPI.

    L'instrumentation 0.65b0 ne passe pas par ``add_middleware`` : elle patche
    ``app.build_middleware_stack`` et pose le drapeau
    ``_is_instrumented_by_opentelemetry``. L'exporter console évite toute
    dépendance réseau ; les instrumentations globales (httpx, SQLAlchemy) sont
    retirées en fin de test pour ne pas fuir sur les autres tests.
    """

    def test_app_instrumentee_puis_retiree(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

        monkeypatch.setattr(settings, "OTEL_ENABLED", True)
        monkeypatch.setattr(settings, "OTEL_METRICS_ENABLED", False)
        monkeypatch.setattr(settings, "OTEL_TRACES_EXPORTER", "console")
        app = FastAPI()

        try:
            setup_telemetry(app)
            assert getattr(app, "_is_instrumented_by_opentelemetry", False)
            assert hasattr(app, "_original_build_middleware_stack")
            # Traces seules : pas d'endpoint de métriques.
            assert all(getattr(r, "path", None) != "/metrics" for r in app.routes)
        finally:
            HTTPXClientInstrumentor().uninstrument()
            SQLAlchemyInstrumentor().uninstrument()
            FastAPIInstrumentor.uninstrument_app(app)


class TestMetricsEndpoint:
    """Métriques seules activées : /metrics répond au format Prometheus, avec
    des labels templatés sans ID réel, et les traces restent no-op.

    Le mode des conventions sémantiques est mémorisé au premier instrument du
    process : on force sa relecture pour obtenir les conventions stables
    (label http_route), comme au démarrage réel de l'app.
    """

    async def test_metrics_exposees_labels_templates(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from opentelemetry.instrumentation._semconv import (
            _OpenTelemetrySemanticConventionStability,
        )
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

        monkeypatch.setattr(settings, "OTEL_ENABLED", False)
        monkeypatch.setattr(settings, "OTEL_METRICS_ENABLED", True)
        monkeypatch.setenv("OTEL_SEMCONV_STABILITY_OPT_IN", "http")
        monkeypatch.setattr(
            _OpenTelemetrySemanticConventionStability, "_initialized", False
        )

        app = FastAPI()

        @app.get("/clients/{id_client}")
        async def get_client(id_client: int) -> dict[str, int]:
            return {"id": id_client}

        try:
            setup_telemetry(app)
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                reponse = await client.get("/clients/987654321")
                assert reponse.status_code == 200
                metrics = await client.get("/metrics")

            assert metrics.status_code == 200
            assert metrics.headers["content-type"].startswith("text/plain")
            corps = metrics.text
            # Histogramme HTTP présent, labellé par la route templatée.
            assert "http_server_request_duration_seconds" in corps
            assert 'http_route="/clients/{id_client}"' in corps
            # Jamais l'identifiant réel dans les labels.
            assert "987654321" not in corps
        finally:
            HTTPXClientInstrumentor().uninstrument()
            SQLAlchemyInstrumentor().uninstrument()
            FastAPIInstrumentor.uninstrument_app(app)

    async def test_scrape_de_metrics_non_compte(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Le scrape de /metrics ne doit pas alimenter ses propres compteurs."""
        from opentelemetry.instrumentation._semconv import (
            _OpenTelemetrySemanticConventionStability,
        )
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

        monkeypatch.setattr(settings, "OTEL_ENABLED", False)
        monkeypatch.setattr(settings, "OTEL_METRICS_ENABLED", True)
        monkeypatch.setenv("OTEL_SEMCONV_STABILITY_OPT_IN", "http")
        monkeypatch.setattr(
            _OpenTelemetrySemanticConventionStability, "_initialized", False
        )
        app = FastAPI()

        try:
            setup_telemetry(app)
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                await client.get("/metrics")
                metrics = await client.get("/metrics")

            assert 'http_route="/metrics"' not in metrics.text
        finally:
            HTTPXClientInstrumentor().uninstrument()
            SQLAlchemyInstrumentor().uninstrument()
            FastAPIInstrumentor.uninstrument_app(app)
