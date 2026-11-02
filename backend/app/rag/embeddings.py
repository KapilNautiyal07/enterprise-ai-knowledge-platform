import os

from fastembed import TextEmbedding


# ONNX build of all-MiniLM-L6-v2: same vectors as the sentence-transformers
# model, without the PyTorch runtime, so the API fits on small instances.
model = TextEmbedding(
    "sentence-transformers/all-MiniLM-L6-v2",
    cache_dir=os.getenv("MODEL_CACHE_DIR", "model_cache"),
    threads=1
)


def generate_embedding(text: str) -> list[float]:

    embedding = next(
        model.embed([text])
    )

    return embedding.tolist()
