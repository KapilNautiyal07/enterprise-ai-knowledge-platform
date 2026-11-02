
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.rag.retrieval import document_chunks, hybrid_reranked_search
from app.rag.context_builder import build_context
from app.rag.generation import LLMGenerationError, generate_answer
from app.rag.citation_validator import validate_citations

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/ask",
    tags=["RAG Question Answering"]
)

class AskRequest(BaseModel):
    query: str = Field(min_length=3, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=10)
    # Restrict answers to these documents; all documents when omitted.
    document_ids: list[UUID] | None = Field(default=None, max_length=50)


# Selected documents up to this size are read in full (better summaries).
FULL_DOCUMENT_CHUNKS = 15


@router.post("/")
def ask_question(
    request: AskRequest,
    db: Session = Depends(get_db)
):
    try:
        # 1. Read small selected documents in full; otherwise retrieve
        #    and rerank the most relevant chunks.
        results = None

        if request.document_ids:
            results = document_chunks(
                db=db,
                document_ids=request.document_ids,
                max_chunks=FULL_DOCUMENT_CHUNKS
            )

        if results is None:
            results = hybrid_reranked_search(
                db=db,
                query=request.query,
                top_k=request.top_k,
                candidate_k=20,
                document_ids=request.document_ids
            )

        # 2. Assemble evidence and source metadata.
        assembled = build_context(results)

        if not assembled["sources"]:
            answer = (
                "I couldn't find relevant evidence in the available documents "
                "to answer this question."
            )
            citation_validation = validate_citations(
                answer=answer,
                sources=[],
            )
            return {
                "query": request.query,
                "answer": answer,
                "sources": [],
                "retrieved_chunks": len(results),
                "context_chunks": 0,
                "citation_validation": citation_validation
            }

        # 3. Generate a grounded answer.
        answer = generate_answer(
            query=request.query,
            context=assembled["context"]
        )

        # 4. Validate citations against available sources.
        citation_validation = validate_citations(
            answer=answer,
            sources=assembled["sources"],
        )

        return {
            "query": request.query,
            "answer": answer,
            "sources": assembled["sources"],
            "retrieved_chunks": len(results),
            "context_chunks": len(assembled["sources"]),
            "citation_validation": citation_validation
        }

    except LLMGenerationError as exc:
        logger.exception("LLM generation failed")
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.detail,
        ) from exc
    except Exception as e:
        logger.exception("Error in /ask/ endpoint")
        raise HTTPException(
            status_code=500,
            detail="Question answering failed. Check the backend terminal."
        ) from e
