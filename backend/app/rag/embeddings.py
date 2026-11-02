from sentence_transformers import SentenceTransformer


model = SentenceTransformer(
    "all-MiniLM-L6-v2"
)


def generate_embedding(text: str) -> list[float]:

    embedding = model.encode(
        text,
        normalize_embeddings=True
    )

    return embedding.tolist()