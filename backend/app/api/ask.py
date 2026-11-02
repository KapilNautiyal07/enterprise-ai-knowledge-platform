
import json
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.rag.retrieval import document_chunks, hybrid_reranked_search, latest_document_id
from app.rag.context_builder import build_context
from app.rag.generation import (
    LLMGenerationError,
    generate_answer,
    is_summary_request,
    stream_answer,
)
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


# Selected documents up to this size are read in full.
FULL_DOCUMENT_CHUNKS = 15
# Summaries read up to this many chunks, sampled across the whole document.
SUMMARY_CHUNKS = 18

NO_SOURCES_ANSWER = (
    "I couldn't find relevant evidence in the available documents "
    "to answer this question."
)


def gather_evidence(request: AskRequest, db: Session) -> tuple[list, dict]:
    """
    Pick the passages the answer will be based on.

    - Summaries read the selected documents (or the latest upload) end to end.
    - Questions about small selected documents read them in full.
    - Everything else uses hybrid retrieval with reranking.
    """

    document_ids = request.document_ids
    results = None

    if is_summary_request(request.query):
        if not document_ids:
            latest = latest_document_id(db)
            document_ids = [latest] if latest else None
        if document_ids:
            results = document_chunks(
                db=db,
                document_ids=document_ids,
                max_chunks=SUMMARY_CHUNKS,
                spread=True
            )

    elif document_ids:
        results = document_chunks(
            db=db,
            document_ids=document_ids,
            max_chunks=FULL_DOCUMENT_CHUNKS
        )

    if results is None:
        results = hybrid_reranked_search(
            db=db,
            query=request.query,
            top_k=request.top_k,
            candidate_k=20,
            document_ids=document_ids
        )

    return results, build_context(results)


def response_metadata(request: AskRequest, results: list, assembled: dict) -> dict:

    return {
        "query": request.query,
        "sources": assembled["sources"],
        "documents_used": list(dict.fromkeys(
            source["filename"] for source in assembled["sources"]
        )),
        "retrieved_chunks": len(results),
        "context_chunks": len(assembled["sources"]),
    }


@router.post("/")
def ask_question(
    request: AskRequest,
    db: Session = Depends(get_db)
):
    try:
        # 1. Choose the evidence passages.
        results, assembled = gather_evidence(request, db)
        metadata = response_metadata(request, results, assembled)

        # 2. Generate a grounded answer.
        answer = (
            generate_answer(
                query=request.query,
                context=assembled["context"]
            )
            if assembled["sources"]
            else NO_SOURCES_ANSWER
        )

        # 3. Validate citations against available sources.
        return {
            **metadata,
            "answer": answer,
            "citation_validation": validate_citations(
                answer=answer,
                sources=assembled["sources"],
            )
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


@router.post("/stream")
def ask_question_stream(
    request: AskRequest,
    db: Session = Depends(get_db)
):
    """
    Same as /ask/, but streams newline-delimited JSON events so the answer
    appears as it is written:

    {"type": "meta", ...sources}  ->  {"type": "delta", "text": ...} (many)
    ->  {"type": "done", "answer": ..., "citation_validation": ...}
    or  {"type": "error", "status": ..., "detail": ...}
    """

    # Database work happens before streaming starts.
    try:
        results, assembled = gather_evidence(request, db)
    except Exception as e:
        logger.exception("Error in /ask/stream retrieval")
        raise HTTPException(
            status_code=500,
            detail="Question answering failed. Check the backend terminal."
        ) from e

    metadata = response_metadata(request, results, assembled)

    def events():
        yield json.dumps({"type": "meta", **metadata}) + "\n"

        pieces = []
        try:
            if assembled["sources"]:
                for piece in stream_answer(request.query, assembled["context"]):
                    pieces.append(piece)
                    yield json.dumps({"type": "delta", "text": piece}) + "\n"
            else:
                pieces.append(NO_SOURCES_ANSWER)
                yield json.dumps({"type": "delta", "text": NO_SOURCES_ANSWER}) + "\n"
        except LLMGenerationError as exc:
            logger.exception("LLM generation failed")
            yield json.dumps({"type": "error", "status": exc.status_code, "detail": exc.detail}) + "\n"
            return
        except Exception:
            logger.exception("Error while streaming answer")
            yield json.dumps({"type": "error", "status": 500, "detail": "Question answering failed."}) + "\n"
            return

        answer = "".join(pieces).strip()
        yield json.dumps({
            "type": "done",
            "answer": answer,
            "citation_validation": validate_citations(
                answer=answer,
                sources=assembled["sources"],
            ),
        }) + "\n"

    return StreamingResponse(
        events(),
        media_type="application/x-ndjson",
        # Ask proxies not to buffer, so pieces reach the browser immediately.
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
