# RAG API

[![CI](https://img.shields.io/github/actions/workflow/status/KulakovVladislav/rag-api/ci.yml?branch=main&label=CI)](https://github.com/KulakovVladislav/rag-api/actions)

A production-ready Retrieval-Augmented Generation API built with **FastAPI**, **PostgreSQL + pgvector**, and **local
sentence-transformers** embeddings. Upload documents, search them semantically — no OpenAI key required.

---

## Table of Contents

- [Overview](#overview)
- [Tech Stack](#tech-stack)
- [Architecture](#architecture)
- [Project Structure](#project-structure)
- [Getting Started](#getting-started)
- [API Reference](#api-reference)
- [Running Tests](#running-tests)
- [Environment Variables](#environment-variables)
- [Engineering Decisions](#engineering-decisions)

---

## Overview

RAG API implements the core pipeline of a document question-answering system:

- Documents are ingested, chunked, and converted into vector embeddings
- Semantic search finds the most relevant chunks via cosine similarity
- Everything runs locally — embeddings are generated with `sentence-transformers` (`all-MiniLM-L6-v2`)

---

## Tech Stack

| Layer          | Technology                                 |
|----------------|--------------------------------------------|
| API            | FastAPI + Gunicorn / Uvicorn               |
| Vector Storage | PostgreSQL 17 + pgvector                   |
| Embeddings     | sentence-transformers (`all-MiniLM-L6-v2`) |
| Cache          | Redis                                      |
| Migrations     | Alembic                                    |
| Reverse Proxy  | Nginx                                      |
| Infrastructure | Docker Compose                             |
| Testing        | Pytest + isolated PostgreSQL container     |

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
  → chunk_text()         — splits content into overlapping chunks
  → generate_embeddings() — encodes chunks via sentence-transformers
  → store               — saves chunks to PostgreSQL with vector(384) column

GET /api/search?q=...
  → encode query         — converts query to vector
  → cosine search        — pgvector <=> operator finds nearest neighbors
  → return top-k chunks  — ranked by similarity score
```

---

## Project Structure

```
rag-api/
├── app/
│   ├── api/
│   │   ├── documents.py          # POST /api/documents
│   │   └── search.py             # GET /api/search
│   ├── database/
│   │   ├── models.py             # Document, Chunk SQLAlchemy models
│   │   ├── db.py                 # Session management
│   │   └── base.py               # Declarative base
│   ├── services/
│   │   ├── embedding_service.py  # sentence-transformers wrapper
│   │   └── chunking_service.py   # Text chunking logic
│   ├── config.py                 # Pydantic settings
│   └── main.py                   # FastAPI app, router registration
├── alembic/                      # Database migrations
├── tests/                        # Pytest test suite
├── docker-compose.yml            # Production stack
├── docker-compose.test.yml       # Isolated test stack
├── Dockerfile                    # Multi-stage, non-root
└── nginx.conf                    # Rate limiting, proxy config
```

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

Ingest a document — chunks it, generates embeddings, and stores everything in PostgreSQL.

**Request**

```json
{
  "title": "FastAPI Guide",
  "content": "FastAPI is a modern..."
}
```

**Response `201`**

```json
{
  "id": 1,
  "title": "FastAPI Guide",
  "chunk_count": 4
}
```

---

### `GET /api/search`

Semantic search over stored chunks.

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

## Running Tests

Tests run against an isolated PostgreSQL container with `tmpfs` — no persistent data, no side effects.

```bash
docker compose -f docker-compose.test.yml up --build --abort-on-container-exit
```

---

## Environment Variables

See `.env.example` for all required variables with descriptions.

---

## Engineering Decisions

**pgvector over a dedicated vector DB (Pinecone, Weaviate)**

At this scale, PostgreSQL + pgvector eliminates the operational overhead of running a separate service. The HNSW index
delivers sub-millisecond search. A dedicated vector DB becomes worthwhile at 10M+ vectors or when multi-tenancy grows
complex.

**Local sentence-transformers over OpenAI embeddings**

Zero API cost, zero external dependency, fully reproducible results. `all-MiniLM-L6-v2` produces 384-dimensional
embeddings — smaller and faster than OpenAI's 1536-dimensional `text-embedding-ada-002`, with comparable quality for
English retrieval.

**HNSW index over IVFFlat**

HNSW builds incrementally and works on an empty table. IVFFlat requires a `VACUUM ANALYZE` after bulk inserts to build
clusters. HNSW uses more memory but delivers better query-time performance and simpler operational behaviour.

---

## Author

**Vladislav** — Backend Engineering · AI Systems · Vector Search
