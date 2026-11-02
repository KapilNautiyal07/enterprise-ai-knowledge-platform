import hashlib


def chunk_text(
    text: str,
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
) -> list[str]:

    if not text.strip():
        return []

    chunks = []

    start = 0
    text_length = len(text)

    while start < text_length:

        end = start + chunk_size

        chunk = text[start:end].strip()

        if chunk:
            chunks.append(chunk)

        start += chunk_size - chunk_overlap

    return chunks


def content_fingerprint(chunks: list[str]) -> str:
    """Stable hash of a document's chunks, used to detect duplicate uploads."""

    return hashlib.sha256(
        "\n".join(chunks).encode("utf-8")
    ).hexdigest()
