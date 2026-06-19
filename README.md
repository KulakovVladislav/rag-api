# RAG API

[![CI](https://img.shields.io/github/actions/workflow/status/KulakovVladislav/rag-api/ci.yml?branch=main&label=CI)](https://github.com/KulakovVladislav/rag-api/actions)

A production-ready Retrieval-Augmented Generation API built with **FastAPI**, **PostgreSQL + pgvector**, and **local
sentence-transformers** embeddings. Upload documents, search them semantically — no OpenAI key required.

Document ingestion is **asynchronous**: `POST /api/documents` returns immediately while chunking and embedding run
in the background, so a 50-page document no longer ties up a Gunicorn worker for 10+ seconds.

---

## Table of Contents

- [Overview](#overview)
- [Tech Stack](#tech-stack)
- [Architecture](#architecture)
- [Async Document Processing](#async-document-processing)
- [Project Structure](#project-structure)
- [Getting Started](#getting-started)
- [API Reference](#api-reference)
- [Running Tests](#running-tests)
- [Environment Variables](#environment-variables)
- [Engineering Decisions](#engineering-decisions)
- [Ticket Status](#ticket-status)
- [CS Answers](./CS_ANSWERS.md)

---

## Overview

RAG API implements the core pipeline of a document question-answering system:

- Documents are accepted instantly, then chunked and embedded **in the background**
- Document status (`processing` / `completed` / `failed`) tracks ingestion progress
- Semantic search finds the most relevant chunks via cosine similarity, and only ever searches `completed` documents
- Everything runs locally — embeddings are generated with `sentence-transformers` (`all-MiniLM-L6-v2`)

---

## Tech Stack

| Layer           | Technology                                 |
|-----------------|--------------------------------------------|
| API             | FastAPI + Gunicorn / Uvicorn               |
| Background Jobs | FastAPI `BackgroundTasks`                  |
| Vector Storage  | PostgreSQL 17 + pgvector                   |
| Embeddings      | sentence-transformers (`all-MiniLM-L6-v2`) |
| Cache           | Redis                                      |
| Migrations      | Alembic                                    |
| Reverse Proxy   | Nginx                                      |
| Infrastructure  | Docker Compose                             |
| Testing         | Pytest + isolated PostgreSQL container     |

---

## Architecture

```
        Client
          │
          ▼ [Port 8080]
┌─────────────────────────┐
│   Nginx (Rate Limiting) │
└────────────┬────────────┘
             │ [Port 8000 – internal]
┌────────────▼────────────┐
│   FastAPI Application   │
│  (Gunicorn + Uvicorn)   │
└──────┬──────────┬───────┘
       │          │
┌──────▼───┐  ┌──▼─────┐
│ Postgres  │  │ Redis  │
│ pgvector  │  │ Cache  │
└──────────┘  └────────┘
```

### RAG Pipeline

```
POST /api/documents
  → insert document, status="processing"
  → return 202 immediately            — client is never blocked on embedding
  → [background] chunk_text()         — splits content into overlapping chunks
  → [background] get_embeddings()     — encodes chunks via sentence-transformers
  → [background] store chunks         — saves to PostgreSQL with vector(384) column
  → [background] status="completed" (or "failed" on exception)

GET /api/search?q=...
  → encode query         — converts query to vector
  → cosine search        — pgvector <=> operator, joined and filtered on status="completed"
  → return top-k chunks  — ranked by similarity score
```

---

## Async Document Processing

`POST /api/documents` no longer does chunking and embedding inline. It creates the document row with
`status="processing"`, schedules the work via FastAPI `BackgroundTasks`, and returns `202 Accepted` right away.

```
POST /api/documents  →  202 {"id": 7, "title": "...", "status": "processing", "chunk_count": 0}

  ... background task runs (chunk → embed → save chunks) ...

GET /api/documents/7  →  200 {"id": 7, ..., "status": "completed", "chunk_count": 4}
```

**Document lifecycle (finite state machine)**

```
processing ──success──▶ completed
    │
    └────failure────▶ failed
```

A document never silently disappears between states — any exception during background processing is caught,
logged with `request_id`, and the document is explicitly marked `failed` rather than being left stuck in
`processing` forever.

**Why a background task instead of Celery?** `BackgroundTasks` runs in the same process and event loop as the
API, after the response has already been sent. It's the minimal version of "don't block the request on slow work."
It is **not** real parallelism for CPU-bound work (see [Engineering Decisions](#engineering-decisions) below for
the tradeoff and when this needs to graduate to Celery/RQ + a worker pool).

**Search only returns finished documents.** `GET /api/search` joins `chunks` to `documents` and filters
`status == 'completed'` in SQL, so a query can never return a chunk from a document that's still mid-ingestion or
that failed halfway through.

---

## Project Structure

```
rag-api/
├── app/
│   ├── api/
│   │   ├── documents.py          # POST/GET/DELETE /api/documents, background task trigger
│   │   └── search.py             # GET /api/search (filters status="completed")
│   ├── database/
│   │   ├── models.py             # Document (with status), Chunk SQLAlchemy models
│   │   ├── db.py                 # Session management
│   │   └── base.py               # Declarative base
│   ├── services/
│   │   ├── document_service.py   # get_documents / get_document_by_id / delete_document
│   │   ├── embedding_service.py  # sentence-transformers wrapper
│   │   └── chunking_service.py   # Text chunking logic
│   ├── config.py                 # Pydantic settings
│   └── main.py                   # FastAPI app, router registration
├── alembic/                      # Database migrations (incl. status column)
├── tests/                        # Pytest test suite
├── docker-compose.yml            # Production stack
├── docker-compose.test.yml       # Isolated test stack
├── Dockerfile                    # Multi-stage, non-root
├── nginx.conf                    # Rate limiting, proxy config
└── CS_ANSWERS.md                 # Written answers to ticket's CS questions
```

> `process_document_background()` lives in `app/services/document_service.py`; `app/api/documents.py` only wires
> it into the route via `BackgroundTasks`.

---

## Getting Started

```bash
cp .env.example .env
# Edit .env with your values

docker compose up --build
```

|            |                              |
|------------|------------------------------|
| API        | `http://localhost:8080`      |
| Swagger UI | `http://localhost:8080/docs` |

---

## API Reference

### `POST /api/documents`

Accepts a document and schedules chunking + embedding in the background. Returns immediately — does **not**
wait for embedding to finish.

**Request**

```json
{
  "title": "FastAPI Guide",
  "content": "FastAPI is a modern..."
}
```

**Response `202 Accepted`**

```json
{
  "id": 1,
  "title": "FastAPI Guide",
  "status": "processing",
  "chunk_count": 0
}
```

---

### `GET /api/documents/{id}`

Returns the current state of a document, including ingestion status.

**Response `200`**

```json
{
  "id": 1,
  "title": "FastAPI Guide",
  "content": "FastAPI is a modern...",
  "status": "completed",
  "chunk_count": 4
}
```

`status` is one of `processing`, `completed`, `failed`. While `processing`, `chunk_count` is `0`.

---

### `GET /api/documents`

Lists documents with pagination. Each item includes `status` and `chunk_count`.

| Parameter | Type    | Default | Description       |
|-----------|---------|---------|-------------------|
| `limit`   | integer | `10`    | Page size (1–100) |
| `offset`  | integer | `0`     | Pagination offset |

---

### `GET /api/search`

Semantic search over stored chunks. Only searches chunks belonging to `completed` documents.

**Query parameters**

| Parameter | Type    | Default  | Description                 |
|-----------|---------|----------|-----------------------------|
| `q`       | string  | required | Search query                |
| `top_k`   | integer | `5`      | Number of results to return |

**Response `200`**

```json
[
  {
    "chunk_id": 3,
    "document_title": "FastAPI Guide",
    "content": "FastAPI is a modern web framework...",
    "score": 0.12
  }
]
```

> Lower score = higher similarity (cosine distance).

---

### `DELETE /api/documents/{id}`

Deletes a document and its chunks (cascade). Returns `204` on success, `404` if not found.

---

## Running Tests

Tests run against an isolated PostgreSQL container with `tmpfs` — no persistent data, no side effects.

```bash
docker compose -f docker-compose.test.yml up --build --abort-on-container-exit
```

14 tests cover the full async flow: immediate `202`/`processing` response, `completed` status with correct
`chunk_count` once background processing finishes, a mocked-failure path that lands on `status="failed"`, and
search excluding chunks from non-`completed` documents — alongside the original CRUD/validation/error-handling
tests.

---

## Environment Variables

See `.env.example` for all required variables with descriptions.

---

## Engineering Decisions

**pgvector over a dedicated vector DB (Pinecone, Weaviate)**

At this scale, PostgreSQL + pgvector eliminates the operational overhead of running a separate service. The HNSW
index delivers sub-millisecond search. A dedicated vector DB becomes worthwhile at 10M+ vectors or when
multi-tenancy grows complex.

**Local sentence-transformers over OpenAI embeddings**

Zero API cost, zero external dependency, fully reproducible results. `all-MiniLM-L6-v2` produces 384-dimensional
embeddings — smaller and faster than OpenAI's 1536-dimensional `text-embedding-ada-002`, with comparable quality for
English retrieval.

**HNSW index over IVFFlat**

HNSW builds incrementally and works on an empty table. IVFFlat requires a `VACUUM ANALYZE` after bulk inserts to
build clusters. HNSW uses more memory but delivers better query-time performance and simpler operational behaviour.

**`BackgroundTasks` over Celery — for now**

`BackgroundTasks` runs in-process, in the same event loop, after the response is sent. For CPU-bound work like
`sentence-transformers` inference, that means the embedding call occupies the worker — other requests hitting that
same Gunicorn worker queue behind it until embedding finishes (mitigated today by `run_in_threadpool` inside
`embedding_service.py`, which moves the blocking call off the main event loop thread, but it's still bounded by
the same process's thread pool, not truly isolated). A real task queue (Celery/RQ + Redis or RabbitMQ) runs work
in separate processes, so a burst of slow embedding jobs can't starve API request handling at all, and jobs survive
a process restart. `BackgroundTasks` is the right call for getting unblocked today; Celery is the right call once
ingestion volume or embedding latency grows enough that a single failed deploy can't be allowed to drop in-flight
jobs.

**Why an explicit `status` column instead of inferring state from `chunk_count`**

`chunk_count == 0` is ambiguous: it's true both for a document that hasn't started processing yet *and* for one
that failed immediately (e.g., chunking threw before any chunk was created) *and*, by coincidence, for a real edge
case — an empty/degenerate document that legitimately produces zero chunks after `completed` processing. An
explicit `status` column removes the guesswork and the race condition where a client polling on `chunk_count > 0`
would report `completed` prematurely if it caught the document between chunk-row inserts (e.g. after 2 of 4 chunks
were committed, before the final `status="completed"` update lands).

**A fresh DB session for background tasks**

The `Depends(get_db)` session is scoped to the request lifecycle — by the time a `BackgroundTasks` callback runs,
the request has already returned a response and that generator-based session is on its way to being torn down.
Reusing it would mean operating on a session that may already be closed, mid-rollback, or being recycled by
SQLAlchemy's pool for an unrelated request. The background function opens its own session via `get_db()`/
`closing(...)`, independent of any request's lifecycle, and is responsible for its own `commit`/`rollback`.

---

## Ticket Status

Tracking against `ТИКЕТ: Async Document Processing с фоновой обработкой`.

### Done

| AC                          | Description                                                                                                                                                                                                                                                                                           | Status |
|-----------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|--------|
| AC-1                        | `POST /api/documents` returns `202` immediately, body has `id`/`title`/`status`                                                                                                                                                                                                                       | ✅      |
| AC-2                        | `status` column added via Alembic, `server_default='completed'` for existing rows, app-level `default='processing'` for new rows                                                                                                                                                                      | ✅      |
| AC-3                        | `GET /api/documents/{id}` returns `status`; `chunk_count=0` while `processing`                                                                                                                                                                                                                        | ✅      |
| AC-4                        | Successful background run flips status to `completed`, chunks land in DB                                                                                                                                                                                                                              | ✅      |
| AC-5                        | Exception during background processing flips status to `failed`, error logged with `exc_info`                                                                                                                                                                                                         | ✅      |
| AC-6                        | `GET /api/search` excludes non-`completed` documents via SQL `JOIN` + filter (not Python-side filtering)                                                                                                                                                                                              | ✅      |
| Migration default           | Explicit `server_default` for existing rows so old documents stay searchable                                                                                                                                                                                                                          | ✅      |
| AC-7 (tests)                | 4 new tests added (`202`+`processing`, `completed`+`chunk_count` after processing, mocked failure → `failed`, search excludes `processing` chunks). Old `test_post_document_returns_201_with_chunk_count` rewritten to match the `202` contract. 14 tests total, all pre-existing behavior preserved. | ✅      |
| Refactor checklist (Слой 5) | `process_document_background()` moved to `app/services/document_service.py`; `app/api/documents.py` now only imports and wires it into the route.                                                                                                                                                     | ✅      |
| CS-фундамент (Слой 4)       | Written up in [`CS_ANSWERS.md`](./CS_ANSWERS.md): event loop blocking vs. Celery isolation, FSM vs. inferred state race condition, DB session lifecycle.                                                                                                                                              | ✅      |

### Out of scope (by request)

Hard Mode (Слой 7: `GET /api/documents/{id}/status` with `Retry-After`, and the idempotency check for
duplicate in-flight `POST`s) was intentionally left out of this pass.

### Smaller things worth a look

- `process_document_background` opens its session via `closing(next(get_db()))`. This calls `.close()` on exit but
  never resumes the `get_db()` generator past its `yield`, so `get_db()`'s own `try/commit`/`except/rollback`
  logic never executes for this path — the function compensates by calling `db.commit()` / `db.rollback()` itself
  explicitly, which works correctly, but it's a slightly unusual use of the dependency generator. Left as-is since
  it's functionally correct; worth a comment if it trips someone up later.

---

## Author

**Vladislav** — Backend Engineering · AI Systems · Vector Search