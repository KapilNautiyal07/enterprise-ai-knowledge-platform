from sqlalchemy.orm import Session

from app.models.document import DocumentChunk, Document
from app.rag.embeddings import generate_embedding
from sqlalchemy import func

from app.models.document import DocumentChunk, Document
from app.rag.embeddings import generate_embedding
from sqlalchemy.orm import Session

from app.rag.reranker import rerank_chunks

def keyword_search(
    db: Session,
    query: str,
    top_k: int = 5
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
        db.query(
            DocumentChunk,
            Document.filename,
            rank.label("rank")
        )
        .join(
            Document,
            Document.id == DocumentChunk.document_id
        )
        .filter(
            DocumentChunk.search_vector.op("@@")(
                ts_query
            )
        )
        .order_by(
            rank.desc()
        )
        .limit(top_k)
        .all()
    )

    return results

def search_similar_chunks(
    db: Session,
    query: str,
    top_k: int = 5
):
    # Generate embedding for the user's question
    query_embedding = generate_embedding(query)

    # Calculate cosine distance between the query
    # and every stored document chunk
    distance = DocumentChunk.embedding.cosine_distance(
        query_embedding
    )

    results = (
        db.query(
            DocumentChunk,
            Document.filename,
            distance.label("distance")
        )
        .join(
            Document,
            Document.id == DocumentChunk.document_id
        )
        .order_by(distance)
        .limit(top_k)
        .all()
    )

    return results

def hybrid_search(
    db: Session,
    query: str,
    top_k: int = 5,
    candidate_k: int = 10
):
    """
    Combine vector search and keyword search
    using Reciprocal Rank Fusion (RRF).
    """

    vector_results = search_similar_chunks(
        db=db,
        query=query,
        top_k=candidate_k
    )

    keyword_results = keyword_search(
        db=db,
        query=query,
        top_k=candidate_k
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

        chunk_id = str(chunk.id)

        if chunk_id not in fused_results:

            fused_results[chunk_id] = {
                "chunk": chunk,
                "filename": filename,
                "vector_rank": None,
                "keyword_rank": None,
                "rrf_score": 0.0
            }

        fused_results[chunk_id]["vector_rank"] = rank

        fused_results[chunk_id]["rrf_score"] += (
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

        chunk_id = str(chunk.id)

        if chunk_id not in fused_results:

            fused_results[chunk_id] = {
                "chunk": chunk,
                "filename": filename,
                "vector_rank": None,
                "keyword_rank": None,
                "rrf_score": 0.0
            }

        fused_results[chunk_id]["keyword_rank"] = rank

        fused_results[chunk_id]["rrf_score"] += (
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
    candidate_k: int = 20
):
    """
    Hybrid retrieval followed by cross-encoder reranking.
    """

    hybrid_results = hybrid_search(
        db=db,
        query=query,
        top_k=candidate_k
    )

    reranked_results = rerank_chunks(
        query=query,
        results=hybrid_results,
        top_k=top_k
    )

    return reranked_results