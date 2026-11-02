from sqlalchemy import text

from app.core.database import Base, engine

from app.models.document import Document, DocumentChunk
from app.rag.chunker import content_fingerprint


def upgrade_schema(connection):
    """
    Idempotent, backward-compatible schema updates for existing databases.
    """

    connection.execute(
        text(
            "ALTER TABLE documents "
            "ADD COLUMN IF NOT EXISTS content_hash VARCHAR(64)"
        )
    )

    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_documents_content_hash "
            "ON documents (content_hash)"
        )
    )

    # Backfill hashes for documents uploaded before duplicate detection existed.
    missing = connection.execute(
        text(
            "SELECT d.id FROM documents d "
            "WHERE d.content_hash IS NULL "
            "AND EXISTS (SELECT 1 FROM document_chunks c WHERE c.document_id = d.id)"
        )
    ).scalars().all()

    for document_id in missing:

        chunks = connection.execute(
            text(
                "SELECT content FROM document_chunks "
                "WHERE document_id = :id ORDER BY chunk_index"
            ),
            {"id": document_id}
        ).scalars().all()

        connection.execute(
            text(
                "UPDATE documents SET content_hash = :hash WHERE id = :id"
            ),
            {"hash": content_fingerprint(chunks), "id": document_id}
        )


def initialize_database():

    with engine.connect() as connection:

        connection.execute(
            text("CREATE EXTENSION IF NOT EXISTS vector")
        )

        connection.commit()

    Base.metadata.create_all(
        bind=engine
    )

    with engine.connect() as connection:

        upgrade_schema(connection)

        connection.commit()


if __name__ == "__main__":

    initialize_database()

    print("Database initialized successfully.")
