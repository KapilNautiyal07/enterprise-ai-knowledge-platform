from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.document import DocumentChunk, Document
from app.rag.embeddings import generate_embedding
from app.rag.reranker import rerank_chunks


def _restrict(query, document_ids: list[UUID] | None):
    """Limit a chunk query to the selected documents, if any were given."""

    if document_ids:
        query = query.filter(
            DocumentChunk.document_id.in_(document_ids)
        )

    return query


def _unique_by_content(results, top_k: int):
    """
    Drop chunks whose text is identical to a higher-ranked chunk
    (e.g. the same file uploaded twice).
    """

    seen = set()
    unique = []

    for result in results:

        content = result[0].content

        if content in seen:
            continue

        seen.add(content)
        unique.append(result)

        if len(unique) == top_k:
            break

    return unique


def keyword_search(
    db: Session,
    query: str,
    top_k: int = 5,
    document_ids: list[UUID] | None = None
):

    ts_query = func.plainto_tsquery(
        "english",
        query
    )

    rank = func.ts_rank(
        DocumentChunk.search_vector,
        ts_query
    )

    results = (
        _restrict(
            db.query(
                DocumentChunk,
                Document.filename,
                rank.label("rank")
            )
            .join(
                Document,
                Document.id == DocumentChunk.document_id
            ),
            document_ids
        )
        .filter(
            DocumentChunk.search_vector.op("@@")(
                ts_query
            )
        )
        .order_by(
            rank.desc()
        )
        .limit(top_k * 2)
        .all()
    )

    return _unique_by_content(results, top_k)

def search_similar_chunks(
    db: Session,
    query: str,
    top_k: int = 5,
    document_ids: list[UUID] | None = None
):
    # Generate embedding for the user's question
    query_embedding = generate_embedding(query)

    # Calculate cosine distance between the query
    # and every stored document chunk
    distance = DocumentChunk.embedding.cosine_distance(
        query_embedding
    )

    results = (
        _restrict(
            db.query(
                DocumentChunk,
                Document.filename,
                distance.label("distance")
            )
            .join(
                Document,
                Document.id == DocumentChunk.document_id
            ),
            document_ids
        )
        .order_by(distance)
        .limit(top_k * 2)
        .all()
    )

    return _unique_by_content(results, top_k)

def document_chunks(
    db: Session,
    document_ids: list[UUID],
    max_chunks: int,
    spread: bool = False
):
    """
    Return every chunk of the selected documents in reading order.

    When they have more than max_chunks chunks, return None, or with
    spread=True an evenly spaced sample covering beginning to end
    (used for summaries of long documents).
    """

    total = (
        db.query(func.count(DocumentChunk.id))
        .filter(DocumentChunk.document_id.in_(document_ids))
        .scalar()
    )

    if not total or (total > max_chunks and not spread):
        return None

    rows = (
        db.query(
            DocumentChunk,
            Document.filename
        )
        .join(
            Document,
            Document.id == DocumentChunk.document_id
        )
        .filter(DocumentChunk.document_id.in_(document_ids))
        .order_by(
            Document.created_at,
            DocumentChunk.chunk_index
        )
        .all()
    )

    if len(rows) > max_chunks:
        step = len(rows) / max_chunks
        rows = [rows[int(i * step)] for i in range(max_chunks)]

    return [
        {"chunk": chunk, "filename": filename}
        for chunk, filename in rows
    ]

def latest_document_id(db: Session) -> UUID | None:
    """The most recently uploaded document that has readable text."""

    return (
        db.query(Document.id)
        .join(
            DocumentChunk,
            DocumentChunk.document_id == Document.id
        )
        .order_by(Document.created_at.desc())
        .limit(1)
        .scalar()
    )

def hybrid_search(
    db: Session,
    query: str,
    top_k: int = 5,
    candidate_k: int = 10,
    document_ids: list[UUID] | None = None
):
    """
    Combine vector search and keyword search
    using Reciprocal Rank Fusion (RRF).
    """

    vector_results = search_similar_chunks(
        db=db,
        query=query,
        top_k=candidate_k,
        document_ids=document_ids
    )

    keyword_results = keyword_search(
        db=db,
        query=query,
        top_k=candidate_k,
        document_ids=document_ids
    )

    # RRF constant
    rrf_k = 60

    fused_results = {}

    # -------------------------
    # Vector results
    # -------------------------

    for rank, result in enumerate(
        vector_results,
        start=1
    ):

        chunk, filename, distance = result

        # Key by content so identical chunks from duplicate uploads merge.
        key = chunk.content

        if key not in fused_results:

            fused_results[key] = {
                "chunk": chunk,
                "filename": filename,
                "vector_rank": None,
                "keyword_rank": None,
                "rrf_score": 0.0
            }

        if fused_results[key]["vector_rank"] is None:

            fused_results[key]["vector_rank"] = rank

            fused_results[key]["rrf_score"] += (
                1 / (rrf_k + rank)
            )

    # -------------------------
    # Keyword results
    # -------------------------

    for rank, result in enumerate(
        keyword_results,
        start=1
    ):

        chunk, filename, keyword_score = result

        key = chunk.content

        if key not in fused_results:

            fused_results[key] = {
                "chunk": chunk,
                "filename": filename,
                "vector_rank": None,
                "keyword_rank": None,
                "rrf_score": 0.0
            }

        if fused_results[key]["keyword_rank"] is None:

            fused_results[key]["keyword_rank"] = rank

            fused_results[key]["rrf_score"] += (
                1 / (rrf_k + rank)
            )

    # -------------------------
    # Sort by RRF score
    # -------------------------

    ranked_results = sorted(
        fused_results.values(),
        key=lambda item: item["rrf_score"],
        reverse=True
    )

    return ranked_results[:top_k]

def hybrid_reranked_search(
    db: Session,
    query: str,
    top_k: int = 5,
    candidate_k: int = 20,
    document_ids: list[UUID] | None = None
):
    """
    Hybrid retrieval followed by cross-encoder reranking.
    """

    hybrid_results = hybrid_search(
        db=db,
        query=query,
        top_k=candidate_k,
        document_ids=document_ids
    )

    reranked_results = rerank_chunks(
        query=query,
        results=hybrid_results,
        top_k=top_k
    )

    return reranked_results
