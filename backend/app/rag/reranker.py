import os

from fastembed.rerank.cross_encoder import TextCrossEncoder


# ONNX build of cross-encoder/ms-marco-MiniLM-L-6-v2 (identical scores).
MODEL_NAME = "Xenova/ms-marco-MiniLM-L-6-v2"

reranker = TextCrossEncoder(
    MODEL_NAME,
    cache_dir=os.getenv("MODEL_CACHE_DIR", "model_cache"),
    threads=1
)


def rerank_chunks(
    query: str,
    results: list,
    top_k: int = 5
):
    """
    Rerank retrieved chunks using a cross-encoder.
    """

    if not results:
        return []

    passages = [
        item["chunk"].content
        for item in results
    ]

    # Small batches keep peak memory low on 512 MB hosts.
    scores = reranker.rerank(
        query,
        passages,
        batch_size=4
    )

    for item, score in zip(results, scores):
        item["reranker_score"] = float(score)

    ranked_results = sorted(
        results,
        key=lambda item: item["reranker_score"],
        reverse=True
    )

    return ranked_results[:top_k]