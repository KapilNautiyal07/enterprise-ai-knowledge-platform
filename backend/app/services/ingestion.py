import uuid

from sqlalchemy.orm import Session

from app.models.document import Document, DocumentChunk
from app.rag.chunker import content_fingerprint
from app.rag.embeddings import generate_embedding

from sqlalchemy import func


def ingest_document(
    db: Session,
    filename: str,
    file_type: str,
    chunks: list[str],
    document_id: uuid.UUID | None = None
):

    document = Document(
        id=document_id or uuid.uuid4(),
        filename=filename,
        file_type=file_type,
        content_hash=content_fingerprint(chunks)
    )

    db.add(document)

    db.flush()

    for index, chunk in enumerate(chunks):

        embedding = generate_embedding(chunk)

        document_chunk = DocumentChunk(
            document_id=document.id,
            chunk_index=index,
            content=chunk,
            embedding=embedding,
            search_vector=func.to_tsvector(
            "english",
            chunk
            )
        )

        db.add(document_chunk)

    db.commit()

    db.refresh(document)

    return document
