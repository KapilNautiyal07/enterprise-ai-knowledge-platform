from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.rag.retrieval import (
    search_similar_chunks,
    keyword_search,
    hybrid_search,
    hybrid_reranked_search
)


router = APIRouter(
    prefix="/search",
    tags=["Search"]
)


@router.get("/")
def search_documents(
    query: str,
    top_k: int = 5,
    document_ids: list[UUID] | None = Query(None),
    db: Session = Depends(get_db)
):

    results = search_similar_chunks(
        db=db,
        query=query,
        top_k=top_k,
        document_ids=document_ids
    )

    return {
        "query": query,
        "results": [
            {
                "chunk_id": str(chunk.id),
                "document_id": str(chunk.document_id),
                "filename": filename,
                "chunk_index": chunk.chunk_index,
                "similarity": round(
                    1 - float(distance),
                    4
                ),
                "content": chunk.content
            }
            for chunk, filename, distance in results
        ]
    }


@router.get("/keyword")
def keyword_search_documents(
    query: str,
    top_k: int = 5,
    document_ids: list[UUID] | None = Query(None),
    db: Session = Depends(get_db)
):

    results = keyword_search(
        db=db,
        query=query,
        top_k=top_k,
        document_ids=document_ids
    )

    return {
        "query": query,
        "results": [
            {
                "chunk_id": str(chunk.id),
                "document_id": str(chunk.document_id),
                "filename": filename,
                "chunk_index": chunk.chunk_index,
                "keyword_score": float(rank),
                "content": chunk.content
            }
            for chunk, filename, rank in results
        ]
    }

@router.get("/hybrid")
def hybrid_search_documents(
    query: str,
    top_k: int = 5,
    document_ids: list[UUID] | None = Query(None),
    db: Session = Depends(get_db)
):

    results = hybrid_search(
        db=db,
        query=query,
        top_k=top_k,
        document_ids=document_ids
    )

    return {
        "query": query,
        "results": [
            {
                "chunk_id": str(item["chunk"].id),
                "document_id": str(item["chunk"].document_id),
                "filename": item["filename"],
                "chunk_index": item["chunk"].chunk_index,
                "vector_rank": item["vector_rank"],
                "keyword_rank": item["keyword_rank"],
                "rrf_score": round(
                    item["rrf_score"],
                    6
                ),
                "content": item["chunk"].content
            }
            for item in results
        ]
    }

@router.get("/reranked")
def reranked_search_documents(
    query: str,
    top_k: int = 5,
    document_ids: list[UUID] | None = Query(None),
    db: Session = Depends(get_db)
):

    results = hybrid_reranked_search(
        db=db,
        query=query,
        top_k=top_k,
        document_ids=document_ids
    )

    return {
        "query": query,
        "results": [
            {
                "chunk_id": str(item["chunk"].id),
                "document_id": str(item["chunk"].document_id),
                "filename": item["filename"],
                "chunk_index": item["chunk"].chunk_index,
                "vector_rank": item["vector_rank"],
                "keyword_rank": item["keyword_rank"],
                "rrf_score": round(
                    item["rrf_score"],
                    6
                ),
                "reranker_score": round(
                    item["reranker_score"],
                    4
                ),
                "content": item["chunk"].content
            }
            for item in results
        ]
    }