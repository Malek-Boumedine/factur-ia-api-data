import shutil
import uuid
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlmodel.ext.asyncio.session import AsyncSession

from src.auth.dependencies import get_current_user, verify_tenant_access
from src.core.database import get_session
from src.documents.models import Document, StatutDocument
from src.utilisateurs.models import Utilisateur

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
) -> dict[str, Any]:
    """
    Reçoit un fichier (PDF ou Image), le valide, le stocke et crée une entrée en base.
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

    return {
        "message": "Fichier uploadé avec succès",
        "id_document": db_document.id,
        "nom_fichier": db_document.nom_fichier,
        "nom_original": db_document.nom_original,
        "statut": db_document.statut,
    }
