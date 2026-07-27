"""Tests du client sortant vers l'API IA (`trigger_extraction`).

Aucun appel réseau réel : les échanges HTTP passent par un
``httpx.MockTransport`` injecté, qui capture la requête pour vérifier le
multipart (fichier + id_document) et le header d'authentification.
"""

from pathlib import Path

import httpx
from src.core.config import settings
from src.integrations.ia_api.client import trigger_extraction


def _fichier_pdf(tmp_path: Path) -> Path:
    """Crée un faux PDF sur disque pour l'envoi."""
    file_path = tmp_path / "facture.pdf"
    file_path.write_bytes(b"%PDF-1.4 contenu factice")
    return file_path


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
