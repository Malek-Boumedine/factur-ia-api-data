import mimetypes
import shutil
import uuid
from pathlib import Path
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Query,
    Security,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from fastapi.security import APIKeyHeader
from loguru import logger
from sqlalchemy.orm import selectinload
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.auth.dependencies import get_current_user, verify_tenant_access
from src.core.config import settings
from src.core.database import get_session
from src.core.pagination import Page, PaginationParams, paginate
from src.documents.exceptions import DocumentIntrouvableError, DocumentLieAFactureError
from src.documents.models import (
    Document,
    ExtractionOcr,
    StatutDocument,
    StatutExtraction,
)
from src.documents.schemas import DocumentRead, OcrWebhookPayload
from src.documents.service import (
    delete_document,
    dispatch_extraction,
    traiter_callback_ocr,
)
from src.utilisateurs.models import Utilisateur

API_KEY_HEADER = APIKeyHeader(name="X-OCR-Secret-Token", auto_error=True)

router = APIRouter(prefix="/documents", tags=["Documents & OCR"])

entreprise_id_dep = Annotated[int, Depends(verify_tenant_access)]
current_user_dep = Annotated[Utilisateur, Depends(get_current_user)]
session_dep = Annotated[AsyncSession, Depends(get_session)]

UPLOAD_DIR = Path("uploads/documents")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@router.post("/upload", status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    session: session_dep,
    current_user: current_user_dep,
    id_entreprise: entreprise_id_dep,
    file: Annotated[UploadFile, File(...)],
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    """
    Reçoit un fichier (PDF ou Image), le valide, le stocke et crée une entrée en base.

    Déclenche ensuite l'extraction OCR en tâche de fond : la réponse est
    renvoyée sans attendre l'API IA, qui rappellera le webhook OCR.
    """
    if current_user.id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Utilisateur non identifié.",
        )

    # 1. Validation du type MIME
    allowed_types = ["application/pdf", "image/jpeg", "image/png"]
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Seuls les PDF, JPG et PNG sont autorisés.",
        )

    # 2. Génération d'un nom de fichier sécurisé et unique
    extension = file.filename.split(".")[-1].lower() if file.filename else "pdf"
    nom_fichier_securise = f"{uuid.uuid4().hex}.{extension}"
    chemin_complet = UPLOAD_DIR / nom_fichier_securise

    # 3. Écriture du fichier sur le disque
    try:
        with open(chemin_complet, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erreur lors de l'enregistrement du fichier sur le serveur.",
        ) from e
    finally:
        file.file.close()

    # 4. Enregistrement en base de données
    db_document = Document(
        id_entreprise=id_entreprise,
        id_utilisateur=current_user.id,
        nom_fichier=nom_fichier_securise,
        nom_original=file.filename or "document_sans_nom.pdf",
        statut=StatutDocument.EN_ATTENTE,
    )

    session.add(db_document)
    await session.commit()
    await session.refresh(db_document)

    # 5. Déclenchement de l'extraction OCR après l'envoi de la réponse
    if db_document.id is not None:
        background_tasks.add_task(dispatch_extraction, db_document.id, chemin_complet)

    return {
        "message": "Fichier uploadé avec succès",
        "id_document": db_document.id,
        "nom_fichier": db_document.nom_fichier,
        "nom_original": db_document.nom_original,
        "statut": db_document.statut,
    }


@router.get("/", response_model=Page[DocumentRead])
async def list_documents(
    session: session_dep,
    id_entreprise: entreprise_id_dep,
    pagination: Annotated[PaginationParams, Depends()],
    statut: Annotated[
        StatutDocument | None,
        Query(description="Filtre sur le statut du document (ex: en_attente, traité)."),
    ] = None,
) -> Any:
    """
    Liste les documents uploadés de l'entreprise active, avec filtre par
    statut et pagination — les plus récents d'abord. Le filtre s'applique
    toujours à l'intérieur du périmètre de l'entreprise (isolation tenant).

    Chaque élément expose ``id_facture`` : l'id du brouillon généré par
    l'OCR pour un document traité, null sinon (même sémantique que la
    route de suivi).
    """
    # Eager load des extractions : id_facture se résout sans requête par ligne.
    statement = (
        select(Document)
        .where(Document.id_entreprise == id_entreprise)
        .options(selectinload(Document.extractions))  # type: ignore
    )
    if statut is not None:
        statement = statement.where(Document.statut == statut)
    statement = statement.order_by(
        col(Document.date_chargement).desc(), col(Document.id).desc()
    )

    page = await paginate(session, statement, pagination)
    page.items = [DocumentRead.from_document(document) for document in page.items]
    return page


@router.get("/{id_document}", response_model=DocumentRead)
async def get_document(
    id_document: int,
    session: session_dep,
    id_entreprise: entreprise_id_dep,
) -> Any:
    """
    Récupère l'état d'un document en s'assurant qu'il appartient bien à
    l'entreprise active (isolation des données).

    Pensée pour le polling du front pendant l'extraction : le statut évolue
    de `en_attente` à `en_cours` puis `traité` ou `erreur`. Quand le document
    est traité, `id_facture` pointe vers le brouillon généré par l'OCR.
    """
    statement = select(Document).where(
        Document.id == id_document, Document.id_entreprise == id_entreprise
    )
    result = await session.exec(statement)
    db_document = result.first()

    if not db_document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document introuvable dans cet espace entreprise",
        )

    # L'id de facture vit sur l'extraction réussie la plus récente : une
    # extraction en échec ne porte jamais d'id_facture et est exclue du filtre.
    id_facture: int | None = None
    if db_document.statut == StatutDocument.TRAITE:
        result_extraction = await session.exec(
            select(ExtractionOcr.id_facture)
            .where(
                ExtractionOcr.id_document == id_document,
                ExtractionOcr.statut == StatutExtraction.SUCCES,
            )
            .order_by(
                col(ExtractionOcr.date_extraction).desc(),
                col(ExtractionOcr.id).desc(),
            )
        )
        id_facture = result_extraction.first()

    return {
        "id": db_document.id,
        "nom_original": db_document.nom_original,
        "statut": db_document.statut,
        "date_chargement": db_document.date_chargement,
        "id_facture": id_facture,
    }


@router.get("/{id_document}/fichier", response_class=FileResponse)
async def get_document_file(
    id_document: int,
    session: session_dep,
    id_entreprise: entreprise_id_dep,
) -> FileResponse:
    """
    Renvoie le fichier original d'un document (PDF ou image), en streaming,
    après vérification qu'il appartient bien à l'entreprise active
    (isolation des données : même 404 indistinct que la route de suivi).

    Le chemin est reconstruit depuis le nom stocké en base (jamais depuis
    une entrée client) et doit rester sous le répertoire d'upload : un
    enregistrement corrompu ne permet pas de lire ailleurs sur le disque.
    """
    statement = select(Document).where(
        Document.id == id_document, Document.id_entreprise == id_entreprise
    )
    result = await session.exec(statement)
    db_document = result.first()

    if not db_document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document introuvable dans cet espace entreprise",
        )

    upload_dir = UPLOAD_DIR.resolve()
    chemin_fichier = (upload_dir / db_document.nom_fichier).resolve()
    if not chemin_fichier.is_relative_to(upload_dir) or not chemin_fichier.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Fichier introuvable sur le serveur",
        )

    media_type = (
        mimetypes.guess_type(db_document.nom_fichier)[0] or "application/octet-stream"
    )
    return FileResponse(
        path=chemin_fichier,
        media_type=media_type,
        filename=db_document.nom_original,
        content_disposition_type="inline",
    )


@router.delete("/{id_document}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document_endpoint(
    id_document: int,
    session: session_dep,
    id_entreprise: entreprise_id_dep,
) -> None:
    """
    Supprime un document uploadé, ses extractions OCR et son fichier physique.

    Refusé (409) si une facture — brouillon ou validée — référence le
    document : le brouillon doit être supprimé d'abord ; une facture validée,
    immuable, impose de conserver le document (trace pour l'audit comptable).

    Le fichier physique n'est supprimé qu'après le commit réussi : une
    transaction échouée ne laisse jamais un enregistrement sans fichier.
    Un fichier déjà absent du disque n'empêche pas la suppression (204).
    """
    try:
        nom_fichier = await delete_document(
            session=session,
            id_document=id_document,
            id_entreprise=id_entreprise,
        )
    except DocumentIntrouvableError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except DocumentLieAFactureError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e

    # Même garde anti-traversal que la route fichier : un nom corrompu en
    # base ne doit pas permettre de supprimer un fichier hors du répertoire.
    upload_dir = UPLOAD_DIR.resolve()
    chemin_fichier = (upload_dir / nom_fichier).resolve()
    if chemin_fichier.is_relative_to(upload_dir):
        try:
            chemin_fichier.unlink(missing_ok=True)
        except OSError:
            logger.warning(
                "Fichier {} du document {} non supprimé du disque",
                nom_fichier,
                id_document,
            )


@router.post("/webhook/ocr", status_code=status.HTTP_200_OK)
async def webhook_ocr_result(
    payload: OcrWebhookPayload,
    session: session_dep,
    api_key: str = Security(API_KEY_HEADER),
) -> dict[str, Any]:
    """
    Réceptionne les résultats de l'IA.

    Génère automatiquement un brouillon de facture à partir des données
    extraites et lie l'extraction à ce brouillon. Si les données sont
    inexploitables, le document passe en erreur et l'extraction en échec.
    """
    # 1. Vérification de sécurité
    if api_key != settings.SECRET_OCR_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token IA invalide ou manquant.",
        )

    # 2. Orchestration : création auto du brouillon + traçage de l'extraction
    try:
        extraction = await traiter_callback_ocr(session, payload)
    except DocumentIntrouvableError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e

    return {
        "message": "Résultats OCR intégrés avec succès",
        "id_extraction": extraction.id,
        "statut": extraction.statut,
        "id_facture": extraction.id_facture,
    }
