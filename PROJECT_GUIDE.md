# Enterprise AI Knowledge Platform Guide

This project is a document-grounded RAG application for enterprise knowledge search and QA. The system takes uploaded documents, converts them to searchable chunks, embeds them, retrieves relevant passages, and answers questions using the retrieved evidence.

## 1. System overview

The application is built around a standard retrieval-augmented generation flow:

1. Upload a document
2. Extract raw text
3. Split into chunks
4. Generate embeddings
5. Store in PostgreSQL with pgvector
6. Retrieve relevant chunks by semantic and keyword search
7. Rerank the best candidates
8. Build evidence context for the model
9. Generate an answer grounded in that evidence
10. Validate citations before returning the answer

## 2. Main architecture

### Backend API layer

Files:
- `backend/app/main.py`
- `backend/app/api/documents.py`
- `backend/app/api/search.py`
- `backend/app/api/ask.py`

Responsibilities:
- expose document upload endpoints
- expose search endpoints
- handle question answering
- validate request payloads and return structured responses

### Data model layer

File:
- `backend/app/models/document.py`

The database contains:
- `Document`: file metadata
- `DocumentChunk`: chunk-level storage for content, embeddings, and search vectors

### Storage and database

Files:
- `backend/app/core/database.py`
- `backend/app/core/init_db.py`
- `backend/app/core/dependencies.py`

Responsibilities:
- create the SQLAlchemy engine
- connect to PostgreSQL
- initialize pgvector
- provide request-scoped DB dependencies

### RAG pipeline

Files:
- `backend/app/rag/chunker.py`
- `backend/app/rag/embeddings.py`
- `backend/app/rag/retrieval.py`
- `backend/app/rag/reranker.py`
- `backend/app/rag/context_builder.py`
- `backend/app/rag/generation.py`
- `backend/app/rag/citation_validator.py`

The pipeline works like this:

- `chunk_text()` splits text into overlapping chunks
- `generate_embedding()` creates vector embeddings
- `search_similar_chunks()` runs vector search
- `keyword_search()` runs lexical search using PostgreSQL full-text search
- `hybrid_search()` combines both using Reciprocal Rank Fusion (RRF)
- `rerank_chunks()` improves rank ordering with a cross-encoder
- `build_context()` arranges the best passages into evidence blocks
- `generate_answer()` sends the evidence to Groq
- `validate_citations()` checks if the answer cites only valid sources

## 3. File ingestion flow

The ingestion path is:

`/documents/upload` -> validate extension -> save to storage -> parse text -> chunk -> embed -> store to PostgreSQL

Supported file types:
- `.pdf`
- `.docx`
- `.txt`

## 4. Retrieval logic

### Vector search

This uses cosine distance between the query embedding and stored chunk embeddings.

### Keyword search

This uses PostgreSQL `tsvector` and `tsquery` with lexical matching.

### Hybrid search

This combines both retrieval strategies to reduce blind spots.

### Reranking

This reorders hybrid candidate results with a cross-encoder, so the model sees the most relevant evidence first.

## 5. Grounded answer generation

The system sends:
- the query
- the retrieved evidence
- a strict system prompt

The prompt instructs the model to:
- use only supplied evidence
- avoid invention
- abstain when information is missing
- cite passages using labels like `[S1]`

This keeps responses grounded rather than speculative.

## 6. Evaluation strategy

The evaluation harness is in:
- `backend/evaluation/evaluate_rag.py`
- `backend/evaluation/evaluation_cases.json`

It checks:
- whether the answer abstains correctly when the evidence does not support a claim
- whether citations are present when they should be
- whether the response includes expected keywords for a case

### Why the evaluator was failing

The original logic had two issues:
1. It used a too-narrow abstention regex
2. It treated citations as required even when the correct answer is a valid abstention

We fixed this by:
- accepting more valid no-evidence phrases
- searching the full answer text instead of only the start
- allowing abstention cases to pass when the answer explicitly says the evidence does not mention the topic

## 7. Recommended evaluation design

Use a hybrid evaluation model:

- Rule-based checks for objective correctness
- LLM-as-judge for subjective quality

This is the best pattern for enterprise RAG because deterministic checks are reliable, while a judge can rate groundedness, clarity, and completeness.

Good setup:
- Answer model: Groq (`openai/gpt-oss-120b`)
- Judge model: a different Groq model, so the answer model does not grade itself
- Final metric: deterministic rules + judge rubric

## 8. Practical next steps

If you want to improve this project further, the next priorities are:

1. Add stricter answer validation in the API
2. Add a Groq-based judge in the evaluation script
3. Log retrieval metrics and answer quality per case
4. Add a caching layer for repeated queries
5. Move file storage to S3 or Azure Blob in production
6. Add user/session isolation for multi-tenant use

## 9. Fixes already applied

The project has been updated to make the evaluation more realistic and robust:

- broader abstention detection
- more realistic citation evaluation for abstention cases
- stronger system prompt to prefer grounded abstention when evidence is missing
- better alignment between evaluation rules and actual supported answer behavior

## 10. Local run

From the backend folder:

```bash
pip install -r requirements.txt
python app/core/init_db.py
uvicorn app.main:app --reload
```

Then open:

- Swagger docs: `http://127.0.0.1:8000/docs`
- Health check: `http://127.0.0.1:8000/health`

## 11. React frontend

The frontend lives in `frontend/` and is built with React, TypeScript, Vite, and
Tailwind CSS.

Start it after the backend is running:

```bash
cd frontend
copy .env.example .env
npm install
npm run dev
```

Open `http://localhost:5173`.

The frontend uses `VITE_API_URL` for the backend base URL. It defaults to
`http://127.0.0.1:8000`. The API client is in `frontend/src/api.ts`, and the
response/request contracts are in `frontend/src/types.ts`.

The main screen supports:

- document upload through `POST /documents/upload`
- grounded answers through `POST /ask/`
- vector search through `GET /search/`
- keyword search through `GET /search/keyword`
- hybrid search through `GET /search/hybrid`
- reranked search through `GET /search/reranked`

The backend enables CORS for the two local Vite origins. If the frontend is
deployed to another origin, add that origin to the `CORSMiddleware` configuration
in `backend/app/main.py` before deployment.

## 12. Summary

This project is a clean enterprise RAG architecture with:
- ingestion
- semantic retrieval
- keyword retrieval
- hybrid fusion
- reranking
- LLM grounded generation
- citation validation
- evaluation harness

The overall design is sound; the main issues were in the evaluation strictness and grounding instructions, which have now been corrected.
