"""
Client sortant vers l'API IA d'extraction (OCR).

Envoie un document uploadé à l'API IA, qui répond 202 puis traite en tâche de
fond avant de rappeler le webhook OCR (`POST /documents/webhook/ocr`).
"""

import mimetypes
from pathlib import Path

import httpx
from loguru import logger

from src.core.config import settings

TIMEOUT_SECONDS = 10.0


async def trigger_extraction(
    file_path: Path,
    id_document: int,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> bool:
    """
    Déclenche l'extraction OCR d'un document auprès de l'API IA.

    Envoie le fichier en multipart avec l'identifiant du document, le secret
    partagé étant transmis en header. Retourne True si l'API IA a accepté la
    demande, False en cas d'échec (fichier illisible, réseau, timeout, statut
    HTTP d'erreur). Le token n'est jamais journalisé.

    Le paramètre `transport` permet d'injecter un transport httpx factice
    dans les tests ; en production il reste à None (transport par défaut).
    """
    url = f"{settings.IA_API_BASE_URL}/extractions"
    content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"

    try:
        file_content = file_path.read_bytes()
    except OSError:
        logger.exception(
            "Fichier illisible pour l'extraction OCR du document {}", id_document
        )
        return False

    async with httpx.AsyncClient(transport=transport) as client:
        try:
            response = await client.post(
                url,
                files={"file": (file_path.name, file_content, content_type)},
                data={"id_document": str(id_document)},
                headers={"X-OCR-Secret-Token": settings.SECRET_OCR_TOKEN},
                timeout=TIMEOUT_SECONDS,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            # Le message d'erreur httpx ne contient pas les headers : le token
            # ne peut pas fuiter dans les logs.
            logger.error(
                "Échec du déclenchement OCR pour le document {} : {}",
                id_document,
                exc,
            )
            return False

    return True
