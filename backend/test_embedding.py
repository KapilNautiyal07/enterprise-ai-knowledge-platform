from app.rag.embeddings import generate_embedding


text = "Employees must use multi-factor authentication."

embedding = generate_embedding(text)

print("Embedding dimensions:", len(embedding))
print("First 5 values:", embedding[:5])