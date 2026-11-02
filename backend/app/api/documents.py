from pathlib import Path
from uuid import uuid4

from fastapi import (
    APIRouter,
    UploadFile,
    File,
    HTTPException,
    Depends
)

from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.services.document_parser import extract_text
from app.rag.chunker import chunk_text
from app.services.ingestion import ingest_document


router = APIRouter(
    prefix="/documents",
    tags=["Documents"]
)


STORAGE_DIR = Path("storage")

STORAGE_DIR.mkdir(
    parents=True,
    exist_ok=True
)


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):

    allowed_extensions = {
        ".pdf",
        ".docx",
        ".txt"
    }

    extension = Path(
        file.filename
    ).suffix.lower()

    if extension not in allowed_extensions:

        raise HTTPException(
            status_code=400,
            detail="Unsupported file type"
        )

    document_id = str(uuid4())

    file_path = (
        STORAGE_DIR /
        f"{document_id}{extension}"
    )

    contents = await file.read()

    with open(file_path, "wb") as buffer:

        buffer.write(contents)

    try:

        text = extract_text(
            str(file_path)
        )

        chunks = chunk_text(text)

        document = ingest_document(
            db=db,
            filename=file.filename,
            file_type=extension,
            chunks=chunks
        )

    except Exception as error:

        file_path.unlink(
            missing_ok=True
        )

        raise HTTPException(
            status_code=500,
            detail=f"Document processing failed: {error}"
        )

    return {
        "document_id": str(document.id),
        "filename": document.filename,
        "file_type": document.file_type,
        "characters": len(text),
        "chunks": len(chunks),
        "status": "processed"
    }