
def build_context(results: list[dict], max_context_chars: int = 18000):
    """
    Build numbered evidence passages from reranked chunks.
    Returns context text and source metadata.
    """

    passages = []
    sources = []
    used_chars = 0

    for item in results:
        chunk = item["chunk"]
        content = chunk.content.strip()

        if not content:
            continue

        remaining = max_context_chars - used_chars

        if remaining <= 0:
            break

        # Do not split a passage silently in the middle.
        if len(content) > remaining:
            if not passages:
                content = content[:remaining]
            else:
                break

        source_number = len(sources) + 1

        passages.append(
            f"[S{source_number}]\n"
            f"Document: {item['filename']}\n"
            f"Chunk index: {chunk.chunk_index}\n"
            f"Content:\n{content}"
        )

        sources.append({
            "source_id": f"S{source_number}",
            "document_id": str(chunk.document_id),
            "chunk_id": str(chunk.id),
            "filename": item["filename"],
            "chunk_index": chunk.chunk_index,
            "content": content,
            "reranker_score": float(
                item.get("reranker_score", 0.0)
            )
        })

        used_chars += len(content)

    return {
        "context": "\n\n---\n\n".join(passages),
        "sources": sources
    }
