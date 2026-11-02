from pathlib import Path
from uuid import UUID, uuid4

from fastapi import (
    APIRouter,
    UploadFile,
    File,
    HTTPException,
    Depends
)

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.models.document import Document, DocumentChunk
from app.services.document_parser import extract_text
from app.rag.chunker import chunk_text, content_fingerprint
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


def serialize_document(document: Document, chunks: int) -> dict:

    return {
        "document_id": str(document.id),
        "filename": document.filename,
        "file_type": document.file_type,
        "chunks": chunks,
        "created_at": (
            document.created_at.isoformat() + "Z"
            if document.created_at
            else None
        )
    }


@router.get("/")
def list_documents(
    db: Session = Depends(get_db)
):

    rows = (
        db.query(
            Document,
            func.count(DocumentChunk.id).label("chunks")
        )
        .outerjoin(
            DocumentChunk,
            DocumentChunk.document_id == Document.id
        )
        .group_by(Document.id)
        .order_by(Document.created_at.desc())
        .all()
    )

    return {
        "documents": [
            serialize_document(document, chunks)
            for document, chunks in rows
        ]
    }


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

    document_id = uuid4()

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

        if not chunks:

            file_path.unlink(
                missing_ok=True
            )

            raise HTTPException(
                status_code=422,
                detail=(
                    "I couldn't find any readable text in this file. "
                    "If it's a scanned document or an image, try a version "
                    "with selectable text."
                )
            )

        # Re-uploading the same content reuses the existing document
        # instead of storing duplicate passages.
        existing = (
            db.query(Document)
            .filter(
                Document.content_hash == content_fingerprint(chunks)
            )
            .first()
        )

        if existing:

            file_path.unlink(
                missing_ok=True
            )

            return {
                **serialize_document(existing, len(chunks)),
                "characters": len(text),
                "status": "duplicate"
            }

        document = ingest_document(
            db=db,
            filename=file.filename,
            file_type=extension,
            chunks=chunks,
            document_id=document_id
        )

    except HTTPException:

        raise

    except Exception as error:

        file_path.unlink(
            missing_ok=True
        )

        raise HTTPException(
            status_code=500,
            detail=f"Document processing failed: {error}"
        )

    return {
        **serialize_document(document, len(chunks)),
        "characters": len(text),
        "status": "processed"
    }


@router.delete("/{document_id}")
def delete_document(
    document_id: UUID,
    db: Session = Depends(get_db)
):

    document = db.get(Document, document_id)

    if document is None:

        raise HTTPException(
            status_code=404,
            detail="Document not found"
        )

    db.query(DocumentChunk).filter(
        DocumentChunk.document_id == document_id
    ).delete()

    db.delete(document)

    db.commit()

    for stored_file in STORAGE_DIR.glob(f"{document_id}.*"):

        stored_file.unlink(
            missing_ok=True
        )

    return {
        "document_id": str(document_id),
        "status": "deleted"
    }
