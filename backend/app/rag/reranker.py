from sentence_transformers import CrossEncoder


MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"

reranker = CrossEncoder(MODEL_NAME)


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

    pairs = [
        (
            query,
            item["chunk"].content
        )
        for item in results
    ]

    scores = reranker.predict(pairs)

    for item, score in zip(results, scores):
        item["reranker_score"] = float(score)

    ranked_results = sorted(
        results,
        key=lambda item: item["reranker_score"],
        reverse=True
    )

    return ranked_results[:top_k]