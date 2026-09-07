"""Tests du client sortant vers l'API IA (`trigger_extraction`).

Aucun appel réseau réel : les échanges HTTP passent par un
``httpx.MockTransport`` injecté, qui capture la requête pour vérifier le
multipart (fichier + id_document) et les headers d'authentification — le
secret partagé ``X-OCR-Secret-Token`` (contrat entre services, envoyé dans
tous les cas) et, quand l'IAM Cloud Run est activé par monkeypatch, le jeton
d'identité ``X-Serverless-Authorization`` (obtention factice, jamais de
serveur de métadonnées).
"""

import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from src.core.config import settings
from src.integrations import gcp_identity
from src.integrations.ia_api.client import trigger_extraction


def _fichier_pdf(tmp_path: Path) -> Path:
    """Crée un faux PDF sur disque pour l'envoi."""
    file_path = tmp_path / "facture.pdf"
    file_path.write_bytes(b"%PDF-1.4 contenu factice")
    return file_path


@pytest.fixture(autouse=True)
def _cache_jeton_vierge() -> Iterator[None]:
    """Purge le cache de jeton d'identité avant et après chaque test."""
    gcp_identity._cached_token = None
    gcp_identity._cached_expiry = 0.0
    yield
    gcp_identity._cached_token = None
    gcp_identity._cached_expiry = 0.0


async def test_envoi_multipart_avec_token(tmp_path: Path) -> None:
    """La requête part en multipart avec le fichier, l'id et le token."""
    fichier_pdf = _fichier_pdf(tmp_path)
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(202)

    accepted = await trigger_extraction(
        fichier_pdf, 42, transport=httpx.MockTransport(handler)
    )

    assert accepted is True
    request = captured["request"]
    assert request.url == f"{settings.IA_API_BASE_URL}/extractions"
    assert request.headers["X-OCR-Secret-Token"] == settings.SECRET_OCR_TOKEN

    body = request.read()
    assert b'name="file"' in body
    assert b'filename="facture.pdf"' in body
    assert b"%PDF-1.4 contenu factice" in body
    assert b'name="id_document"' in body
    assert b"42" in body


async def test_iam_desactive_aucun_jeton_demande(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """IAM désactivé (défaut) : pas d'en-tête d'identité, aucun jeton demandé,
    et le secret partagé part quand même."""
    monkeypatch.setattr(settings, "IA_API_IAM_AUTH_ENABLED", False)

    def fetch_interdit(*args: Any, **kwargs: Any) -> str:
        raise AssertionError("fetch_id_token ne doit pas être appelé désactivé")

    monkeypatch.setattr(gcp_identity, "fetch_id_token", fetch_interdit)
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(202)

    accepted = await trigger_extraction(
        _fichier_pdf(tmp_path), 42, transport=httpx.MockTransport(handler)
    )

    assert accepted is True
    request = captured["request"]
    assert "X-Serverless-Authorization" not in request.headers
    assert request.headers["X-OCR-Secret-Token"] == settings.SECRET_OCR_TOKEN


async def test_iam_active_jeton_et_secret_partage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """IAM activé : le jeton d'identité part en Bearer, et le secret partagé
    reste envoyé — le contrat entre services n'est pas affecté."""
    monkeypatch.setattr(settings, "IA_API_IAM_AUTH_ENABLED", True)
    monkeypatch.setattr(gcp_identity, "fetch_id_token", lambda *a: "jeton-factice")
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(202)

    accepted = await trigger_extraction(
        _fichier_pdf(tmp_path), 42, transport=httpx.MockTransport(handler)
    )

    assert accepted is True
    request = captured["request"]
    assert request.headers["X-Serverless-Authorization"] == "Bearer jeton-factice"
    assert request.headers["X-OCR-Secret-Token"] == settings.SECRET_OCR_TOKEN


async def test_iam_active_echec_jeton_retourne_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Jeton impossible à obtenir : échec propre (False), aucune requête émise."""
    monkeypatch.setattr(settings, "IA_API_IAM_AUTH_ENABLED", True)

    def fetch_en_echec(*args: Any) -> str:
        raise RuntimeError("serveur de métadonnées injoignable")

    monkeypatch.setattr(gcp_identity, "fetch_id_token", fetch_en_echec)
    requetes: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requetes.append(request)
        return httpx.Response(202)

    accepted = await trigger_extraction(
        _fichier_pdf(tmp_path), 42, transport=httpx.MockTransport(handler)
    )

    assert accepted is False
    assert requetes == []


async def test_jeton_expire_renouvele_entre_deux_envois(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un jeton en cache à moins de 5 min de l'expiration est renouvelé."""
    monkeypatch.setattr(settings, "IA_API_IAM_AUTH_ENABLED", True)
    monkeypatch.setattr(gcp_identity, "fetch_id_token", lambda *a: "jeton-frais")
    # Jeton déjà en cache mais mourant : expire dans 60 s, sous la marge.
    gcp_identity._cached_token = "jeton-mourant"  # noqa: S105  # faux positif
    gcp_identity._cached_expiry = time.time() + 60
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(202)

    accepted = await trigger_extraction(
        _fichier_pdf(tmp_path), 42, transport=httpx.MockTransport(handler)
    )

    assert accepted is True
    header = captured["request"].headers["X-Serverless-Authorization"]
    assert header == "Bearer jeton-frais"


async def test_statut_http_erreur_retourne_false(tmp_path: Path) -> None:
    """Une réponse d'erreur de l'API IA est traitée comme un échec."""
    fichier_pdf = _fichier_pdf(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    accepted = await trigger_extraction(
        fichier_pdf, 42, transport=httpx.MockTransport(handler)
    )

    assert accepted is False


async def test_erreur_reseau_retourne_false(tmp_path: Path) -> None:
    """Une API IA injoignable (erreur réseau) est traitée comme un échec."""
    fichier_pdf = _fichier_pdf(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connexion refusée", request=request)

    accepted = await trigger_extraction(
        fichier_pdf, 42, transport=httpx.MockTransport(handler)
    )

    assert accepted is False


async def test_fichier_illisible_retourne_false(tmp_path: Path) -> None:
    """Un fichier absent du disque n'envoie rien et retourne un échec."""
    accepted = await trigger_extraction(
        tmp_path / "inexistant.pdf",
        42,
        transport=httpx.MockTransport(lambda request: httpx.Response(202)),
    )

    assert accepted is False
