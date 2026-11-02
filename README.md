# Enterprise AI Knowledge Platform

This project is a document-centric RAG (Retrieval-Augmented Generation) system for enterprise knowledge search and question answering. It ingests uploaded documents, chunks them into searchable units, embeds them into a vector space, retrieves the most relevant evidence, and uses a large language model to answer grounded questions with citations.

The system is implemented as a FastAPI backend backed by PostgreSQL with pgvector support. It combines:

- Document ingestion and parsing
- Text chunking and embedding generation
- Hybrid retrieval (vector + keyword search)
- Cross-encoder reranking
- Grounded answer generation with Groq
- Citation validation
- Evaluation against curated Q&A cases

---

## High-level architecture

```text
+-------------------+
| Client / UI / API |
+---------+---------+
          |
          v
+-------------------+
| FastAPI app       |
| app/main.py       |
+---------+---------+
          |
          +------------------------------+
          |                              |
          v                              v
+-------------------+          +-------------------+
| /documents/upload |          | /ask/             |
| file validation   |          | question handling |
| parser + chunker  |          | retrieval + LLM   |
+---------+---------+          +---------+---------+
          |                              |
          |                              v
          |                   +---------------------------+
          |                   | RAG pipeline              |
          |                   | - vector search           |
          |                   | - keyword search          |
          |                   | - hybrid fusion           |
          |                   | - rerank                 |
          |                   | - context assembly        |
          |                   +-------------+-------------+
          |                                 |
          v                                 v
+-------------------+         +----------------------------+
| Storage          |         | PostgreSQL + pgvector      |
| storage/*.pdf    |         | documents                  |
| storage/*.docx   |         | document_chunks            |
| storage/*.txt    |         | embedding + search_vector  |
+-------------------+         +----------------------------+
                                      |
                                      v
                            +--------------------+
                            | Groq LLM           |
                            | generate_answer()  |
                            +---------+----------+
                                      |
                                      v
                            +--------------------+
                            | Citation validation|
                            | validates [S1] etc |
                            +--------------------+
```

---

## Repository structure

```text
enterprise-ai-knowledge-platform/
├── .env                          # runtime environment config
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   ├── ask.py            # question answering endpoint
│   │   │   ├── documents.py      # upload endpoint
│   │   │   └── search.py         # search endpoints
│   │   ├── core/
│   │   │   ├── database.py       # SQLAlchemy engine + session
│   │   │   ├── dependencies.py   # DB dependency
│   │   │   └── init_db.py        # database bootstrap
│   │   ├── models/
│   │   │   └── document.py       # Document + DocumentChunk ORM models
│   │   ├── rag/
│   │   │   ├── chunker.py        # text chunking
│   │   │   ├── context_builder.py# evidence packaging
│   │   │   ├── citation_validator.py
│   │   │   ├── embeddings.py     # all-MiniLM-L6-v2 embeddings (ONNX)
│   │   │   ├── generation.py     # Groq answer generation
│   │   │   ├── reranker.py       # cross-encoder reranking
│   │   │   └── retrieval.py      # vector + keyword + hybrid search
│   │   ├── services/
│   │   │   ├── document_parser.py# PDF/DOCX/TXT text extraction
│   │   │   └── ingestion.py      # stores documents and chunks
│   │   └── main.py              # FastAPI app registration
│   ├── evaluation/
│   │   ├── evaluate_rag.py      # evaluation harness
│   │   ├── evaluation_cases.json# Q&A cases
│   │   └── evaluation_results.json
│   ├── requirements.txt         # Python dependencies
│   ├── storage/                 # uploaded files preserved during processing
│   ├── test_db.py               # DB smoke tests
│   ├── test_embedding.py        # embedding checks
│   └── test_rag_evaluation.py   # evaluation checks
├── README.md
└── .gitignore
```

---

## Runtime pipeline: end-to-end flow

### 1) API entry points

The application exposes three main API groups from `backend/app/main.py`:

- `/documents/upload` — accepts a PDF, DOCX, or TXT file and triggers indexing
- `/search` — performs raw vector, keyword, hybrid, and reranked queries
- `/ask/` — executes the full RAG pipeline and returns an answer with evidence

The root-level routes also expose `/` and `/health` for liveness checks.

### 2) Ingestion pipeline

This is the document-processing path that turns uploaded files into searchable chunk records.

1. Client uploads a file to `/documents/upload`.
2. The route validates the extension and allows only `.pdf`, `.docx`, and `.txt` files.
3. The file is stored under `backend/storage/<uuid><extension>`.
4. `extract_text()` in `app/services/document_parser.py` reads the file and converts it into plain text.
5. `chunk_text()` in `app/rag/chunker.py` splits the text into overlapping chunks.
   - Default chunk size: `1000` characters
   - Default overlap: `200` characters
6. For each chunk, `generate_embedding()` in `app/rag/embeddings.py` creates a semantic vector with `all-MiniLM-L6-v2`.
7. `ingest_document()` in `app/services/ingestion.py` stores:
   - a row in `documents`
   - one row per chunk in `document_chunks`
   - a pgvector embedding in `DocumentChunk.embedding`
   - a PostgreSQL TSVECTOR in `DocumentChunk.search_vector`
8. The database is initialized with the required PostgreSQL extension support via `CREATE EXTENSION IF NOT EXISTS vector` and table creation through SQLAlchemy metadata.

This creates the searchable knowledge store that later queries will use.

### 3) Data model and persistence

The model layer lives in `backend/app/models/document.py`.

```python
class Document:
    - id
    - filename
    - file_type
    - created_at

class DocumentChunk:
    - id
    - document_id -> FK to Document
    - chunk_index
    - content
    - embedding -> Vector(384)
    - search_vector -> TSVECTOR
    - created_at
```

Key storage decisions:

- `Document` stores metadata for each uploaded file.
- `DocumentChunk` stores the actual evidence units and their embeddings.
- `embedding` is a vector representation for semantic similarity.
- `search_vector` supports full-text keyword search using PostgreSQL text search.

### 4) Retrieval pipeline

The retrieval flow is in `backend/app/rag/retrieval.py`.

#### 4.1 Vector retrieval

`search_similar_chunks()`:

- turns the user query into an embedding
- compares it with all stored chunk embeddings using cosine distance
- returns the closest chunks sorted by distance

This gives a semantic search path that finds similar ideas even when phrasing differs.

#### 4.2 Keyword retrieval

`keyword_search()`:

- builds a `plainto_tsquery("english", query)`
- ranks matches with `ts_rank()` against `DocumentChunk.search_vector`
- filters chunks where `search_vector @@ ts_query`

This is useful when the answer depends on exact nouns, terms, policies, or domain language.

#### 4.3 Hybrid retrieval with RRF

`hybrid_search()` combines the vector and keyword results using Reciprocal Rank Fusion (RRF):

```python
score = 1 / (k + rank)
```

The system:

- retrieves candidate results from both vector and keyword search
- fuses ranks into one score per chunk
- returns the highest combined result set

This reduces the risk of relying on only one retrieval mode.

#### 4.4 Cross-encoder reranking

`rerank_chunks()` uses a cross-encoder model (`ms-marco-MiniLM-L-6-v2`, ONNX build via `fastembed`) to evaluate the query against each candidate chunk in context.

This step reorders the hybrid candidate set and helps prioritize the most relevant pieces before they are passed into the LLM.

The endpoint `/search/reranked` exposes this flow directly.

### 5) Context assembly and answer generation

The `/ask/` endpoint in `backend/app/api/ask.py` is the central orchestration point.

Pipeline:

1. `hybrid_reranked_search()` retrieves and reranks the best evidence chunks.
2. `build_context()` in `backend/app/rag/context_builder.py` turns those chunks into:
   - a numbered evidence block (for the LLM)
   - a source metadata list (`S1`, `S2`, etc.)
3. `generate_answer()` in `backend/app/rag/generation.py` calls Groq with:
   - the user's question
   - the context passages
   - a strict system prompt telling the model to answer only from the evidence and cite labels such as `[S1]`
4. `validate_citations()` checks that the answer references only valid source IDs from the assembled context.

This is what makes the system grounded rather than free-form generation.

---

## LLM generation details

The generation layer is configured in `backend/app/rag/embeddings.py` and `backend/app/rag/generation.py`.

### Embeddings

- `all-MiniLM-L6-v2` (384 dimensions), run through `fastembed` with ONNX Runtime
- Produces the same vectors as the `sentence-transformers` model without requiring PyTorch, which keeps memory under ~450 MB
- Used both for indexing stored text chunks and for embedding user queries
- Embeddings are normalized before storage and retrieval

### Language model

- Groq via its OpenAI-compatible API (`openai` SDK, `base_url=https://api.groq.com/openai/v1`)
- Model default: `openai/gpt-oss-120b`
- Configured via `GROQ_API_KEY` and `GROQ_MODEL` from `.env`
- Uses a strict evidence-only system prompt:
  - no invented facts
  - no unsupported claims
  - if evidence is insufficient, say so
  - cite exact labels like `[S1]`

### Citation validation

The citation validator searches for patterns like:

```text
[S1]
[S2, S3]
```

and compares them against the generated evidence set. It then reports:

- `valid`
- `citations_found`
- `valid_citations`
- `invalid_citations`
- `has_citations`
- `citation_coverage`

This provides a lightweight guarantee that the answer references only the evidence that was actually supplied.

---

## API endpoints

### Document ingestion

#### POST `/documents/upload`

Upload a document file.

Request:
- multipart form-data
- field name: `file`

Supported types:
- `.pdf`
- `.docx`
- `.txt`

Response example:

```json
{
  "document_id": "...",
  "filename": "example.pdf",
  "file_type": ".pdf",
  "characters": 12345,
  "chunks": 12,
  "status": "processed"
}
```

If the same content was uploaded before, the existing document is returned with `"status": "duplicate"` and nothing new is stored. Files without extractable text (for example scanned images) are rejected with HTTP 422.

#### GET `/documents/`

Lists uploaded documents (newest first) with their section counts and upload dates.

#### DELETE `/documents/{document_id}`

Removes a document and all of its indexed sections.

### Search endpoints

#### GET `/search/?query=...&top_k=5`

Performs vector similarity search.

#### GET `/search/keyword?query=...&top_k=5`

Performs full-text keyword search.

#### GET `/search/hybrid?query=...&top_k=5`

Runs hybrid vector + keyword retrieval using RRF.

#### GET `/search/reranked?query=...&top_k=5`

Runs hybrid retrieval + cross-encoder reranking.

### Question answering

#### POST `/ask/`

Request body:

```json
{
  "query": "What does the policy say about remote work?",
  "top_k": 5,
  "document_ids": ["..."]
}
```

`document_ids` is optional and limits the answer to those documents. When the selected documents are small (up to 15 sections), they are read in full instead of retrieving the top passages, which gives complete summaries. The search endpoints accept the same filter as repeated `document_ids` query parameters.

Summary requests ("summarize", "overview", "key points", ...) read the selected documents end to end (sampled evenly for long documents), or the most recent upload when nothing is selected, and use a dedicated summary format: title, overview, sections, key takeaways.

#### POST `/ask/stream`

Same request body as `/ask/`, but streams newline-delimited JSON so answers appear as they are written:

```text
{"type": "meta", "sources": [...], "documents_used": [...], ...}
{"type": "delta", "text": "..."}            (repeated)
{"type": "done", "answer": "...", "citation_validation": {...}}
```

Errors during generation are sent as `{"type": "error", "status": ..., "detail": ...}`. The web app uses this endpoint.

Response example:

```json
{
  "query": "What does the policy say about remote work?",
  "answer": "According to the policy, remote work is allowed ... [S2]",
  "sources": [
    {
      "source_id": "S1",
      "document_id": "...",
      "chunk_id": "...",
      "filename": "policy.pdf",
      "chunk_index": 5,
      "reranker_score": 0.92
    }
  ],
  "retrieved_chunks": 5,
  "context_chunks": 2,
  "citation_validation": {
    "valid": true,
    "citations_found": ["S1", "S2"],
    "valid_citations": ["S1", "S2"],
    "invalid_citations": [],
    "has_citations": true,
    "citation_coverage": 1.0
  }
}
```

---

## Data flow summary

The system is a classic retrieval-grounded pipeline:

```text
Document upload
  -> parse text
  -> chunk text
  -> embed chunks
  -> store in PostgreSQL + pgvector

User question
  -> embed query
  -> vector search
  -> keyword search
  -> hybrid fusion
  -> reranking
  -> context assembly
  -> Groq answer generation
  -> citation validation
  -> final response
```

This architecture is designed to prioritize both:

- semantic relevance (vector search)
- exact-match relevance (keyword search)
- answer quality and evidence grounding (rerank + LLM + citation checks)

---

## Evaluation pipeline

The project includes a lightweight evaluation harness in `backend/evaluation/evaluate_rag.py`.

It:

- loads benchmark cases from `evaluation_cases.json`
- calls the live `/ask/` endpoint
- checks answer quality using:
  - expected keywords
  - abstention behavior
  - citation validity
- saves results into `evaluation_results.json`

This is important because the platform is not just a document search engine; it is a grounded-answering system that must be validated against realistic knowledge questions.

---

## Configuration

The platform reads environment variables from the root `.env` file.

Required variables:

```env
DATABASE_URL=...
GROQ_API_KEY=...
GROQ_MODEL=openai/gpt-oss-120b
```

Optional: `FRONTEND_ORIGINS` adds comma-separated frontend URLs to the CORS allow-list (needed when the frontend is deployed).

The application expects PostgreSQL with the pgvector extension enabled. The database bootstrap script creates the extension automatically when initialized.

---

## Local setup

1. Create and activate a Python environment.
2. Install dependencies:

```bash
cd backend
pip install -r requirements.txt
```

3. Ensure your `.env` file contains the required secrets and database URL.
4. Initialize the database:

```bash
cd backend
python app/core/init_db.py
```

5. Start the FastAPI app:

```bash
cd backend
uvicorn app.main:app --reload
```

6. Open the API at:

```text
http://127.0.0.1:8000/docs
```

### Frontend setup

The React frontend is in `frontend/` and uses Vite, TypeScript, and Tailwind CSS.

```bash
cd frontend
copy .env.example .env
npm install
npm run dev
```

The frontend runs at `http://localhost:5173` and calls the backend at
`http://127.0.0.1:8000` by default. Set `VITE_API_URL` in `frontend/.env` when
the backend is hosted elsewhere.

The FastAPI app includes CORS support for the local Vite origins:

- `http://localhost:5173`
- `http://127.0.0.1:5173`

plus any URLs listed in `FRONTEND_ORIGINS`.

The frontend provides:

- PDF, DOCX, and TXT upload and indexing
- cited question answering through `/ask/`
- semantic, keyword, hybrid, and reranked search
- clickable citations that jump to the supporting passage
- plain-language trust notes based on citation validation

---

## Deployment (free tier)

| Part | Service | Notes |
|------|---------|-------|
| Database | [Neon](https://neon.tech) | Serverless PostgreSQL with pgvector |
| Backend | [Render](https://render.com) free web service | Configured by `render.yaml` (512 MB RAM) |
| Frontend | [Vercel](https://vercel.com) | Static Vite build |

### Backend on Render

1. In Render, choose **New > Blueprint** and select this repository. Render reads `render.yaml`.
2. Fill in the secret environment variables when prompted:
   - `DATABASE_URL`: the Neon connection string
   - `GROQ_API_KEY`: the Groq API key
   - `FRONTEND_ORIGINS`: the Vercel URL (can be added after the frontend is deployed)
3. Deploy, then check `https://<service>.onrender.com/health`.

The free instance sleeps after 15 minutes without traffic, so the first request after a pause can take about a minute.
Uploaded files are stored on ephemeral disk; their extracted text and embeddings are kept in the database, so search and answers keep working after restarts.

### Frontend on Vercel

1. Import the repository in Vercel and set **Root Directory** to `frontend` (Vite is detected automatically).
2. Add the environment variable `VITE_API_URL=https://<service>.onrender.com`.
3. Deploy, then add the Vercel URL to `FRONTEND_ORIGINS` on Render.

---

## Design notes and trade-offs

- This system is optimized for enterprise knowledge documents, not for real-time streaming or multi-tenant workloads.
- It stores the raw uploaded files locally in `backend/storage`, which is convenient for development but should be replaced with object storage in production.
- The retrieval stack intentionally combines semantic and lexical methods to reduce blind spots.
- The answer generation path is strongly grounded by requiring the model to cite evidence passages and by validating citations before returning the response.

---

## Practical summary

The architecture follows a standard enterprise RAG pattern:

```text
Upload -> Parse -> Chunk -> Embed -> Index -> Retrieve -> Rerank -> Ground -> Answer
```

The project is built to answer questions from enterprise documents with evidence-backed, source-aware outputs rather than relying on ungrounded model knowledge.

If you want to extend the platform further, the next logical upgrades are:

- async ingestion workers
- document metadata and tagging
- multi-tenant user isolation
- Azure Blob / S3 storage
- monitoring and tracing
- larger vector index strategies for scaling
- evaluation dashboards with recall/precision metrics
