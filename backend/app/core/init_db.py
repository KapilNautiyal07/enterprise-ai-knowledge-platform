from sqlalchemy import text

from app.core.database import Base, engine

from app.models.document import Document, DocumentChunk


def initialize_database():

    with engine.connect() as connection:

        connection.execute(
            text("CREATE EXTENSION IF NOT EXISTS vector")
        )

        connection.commit()

    Base.metadata.create_all(
        bind=engine
    )


if __name__ == "__main__":

    initialize_database()

    print("Database initialized successfully.")