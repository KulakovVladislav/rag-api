<h1 align="center">RAG API</h1>

<p align="center">
  Upload documents. Search them by meaning.<br>
  Runs entirely on your machine — no API keys, no external services.
</p>

<p align="center">
  <a href="https://github.com/KulakovVladislav/rag-api/actions"><img alt="CI" src="https://img.shields.io/github/actions/workflow/status/KulakovVladislav/rag-api/ci.yml?branch=main&label=CI"></a>
</p>

---

RAG API is a Retrieval-Augmented Generation backend built with **FastAPI**, **PostgreSQL + pgvector**, and local
**sentence-transformers** embeddings.

Ingestion is **asynchronous**. `POST /api/documents` returns immediately while chunking and embedding run in the
background, so a 50-page document never ties up a Gunicorn worker for 10+ seconds.

## Highlights

- **Instant uploads.** Documents are accepted right away, then chunked and embedded in the background.
- **Visible progress.** Every document has a status: `processing`, `completed`, or `failed`.
- **No duplicate work.** Identical content is rejected at ingestion via a SHA-256 content hash.
- **Flexible metadata.** Attach any JSON object to a document; it is stored as-is and returned on detail and search
  reads.
- **Semantic search.** Cosine similarity over chunks, restricted to `completed` documents.
- **Fast repeat queries.** Results are cached in Redis and invalidated the moment new content finishes processing.
- **Traceable.** Every request gets a request ID and a timer, carried through to the logs.
- **Production-minded probes.** `/system/live` and `/system/ready` back the Docker healthcheck and gate when Nginx
  starts routing traffic.
- **Fully local.** Embeddings come from `all-MiniLM-L6-v2` via `sentence-transformers`.

## Contents

- [Getting Started](#getting-started)
- [Tech Stack](#tech-stack)
- [Architecture](#architecture)
- [Features](#features)
    - [Async Document Processing](#async-document-processing)
    - [Content Deduplication](#content-deduplication)
    - [Document Metadata](#document-metadata)
    - [Search Result Caching](#search-result-caching)
    - [Observability](#observability)
    - [Health Checks](#health-checks)
    - [Seeding Test Data](#seeding-test-data)
- [API Reference](#api-reference)
- [Project Structure](#project-structure)
- [Running Tests](#running-tests)
- [Environment Variables](#environment-variables)
- [Engineering Decisions](#engineering-decisions)

---

## Getting Started

```bash
cp .env.example .env
# Edit .env with your values

docker compose up --build
```

| Service    | URL                          |
|------------|------------------------------|
| API        | `http://localhost:8080`      |
| Swagger UI | `http://localhost:8080/docs` |

## Tech Stack

| Layer           | Technology                                    |
|-----------------|-----------------------------------------------|
| API             | FastAPI + Gunicorn / Uvicorn                  |
| Background Jobs | FastAPI `BackgroundTasks`                     |
| Vector Storage  | PostgreSQL 17 + pgvector                      |
| Embeddings      | sentence-transformers (`all-MiniLM-L6-v2`)    |
| Cache           | Redis                                         |
| Migrations      | Alembic                                       |
| Reverse Proxy   | Nginx                                         |
| Infrastructure  | Docker Compose                                |
| Testing         | Pytest + isolated PostgreSQL/Redis containers |

---

## Architecture

```text
                 Client
                   │  :8080
                   ▼
  ┌─────────────────────────────────┐
  │      Nginx · rate limiting      │
  └────────────────┬────────────────┘
                   │  :8000 (internal)
  ┌────────────────▼────────────────┐
  │       FastAPI application       │
  │       Gunicorn + Uvicorn        │
  └────────┬───────────────┬────────┘
           │               │
     ┌─────▼────┐     ┌────▼─────┐
     │ Postgres │     │  Redis   │
     │ pgvector │     │  cache   │
     └──────────┘     └──────────┘
```

### RAG pipeline

```text
POST /api/documents
  → insert document, status="processing"
  → return 202 immediately            — the client is never blocked on embedding
  → [background] chunk_text()         — split content into overlapping chunks
  → [background] get_embeddings()     — encode chunks with sentence-transformers
  → [background] bulk insert chunks   — one round trip, one commit
  → [background] status="completed"   — or "failed" on any exception

GET /api/search?q=...
  → encode query                      — convert the query to a vector
  → cosine search                     — pgvector <=>, filtered on status="completed"
  → return top-k chunks               — ranked by similarity score
```

---

## Features

### Async Document Processing

`POST /api/documents` creates the document row with `status="processing"`, schedules the work through FastAPI
`BackgroundTasks`, and returns `202 Accepted` right away.

```text
POST /api/documents  →  202 {"id": 7, "title": "...", "status": "processing", "chunk_count": 0}

  … background task runs: chunk → embed → save chunks …

GET /api/documents/7  →  200 {"id": 7, …, "status": "completed", "chunk_count": 4}
```

**Lifecycle**

```text
processing ──success──▶ completed
    │
    └─────failure─────▶ failed
```

A document never gets stuck. Any exception during background processing is caught, logged with its `request_id`, and the
document is explicitly marked `failed`.

**Why `BackgroundTasks` instead of Celery?** It runs in the same process and event loop as the API, after the response
has been sent: the minimal version of "don't block the request on slow work." It is **not** real parallelism for
CPU-bound work. See [Engineering Decisions](#engineering-decisions) for the trade-off and when to graduate to Celery/RQ.

**Batch inserts.** Once all chunks are embedded, they are written with a single `db.bulk_save_objects(chunks_to_insert)`
and one `commit()` — one round trip to Postgres instead of one `INSERT` per chunk.

**Finished documents only.** `GET /api/search` joins `chunks` to `documents` and filters on `status == 'completed'` in
SQL. A query can never return a chunk from a document that is still mid-ingestion or that failed.

### Content Deduplication

Before scheduling any background work, `POST /api/documents` computes a SHA-256 hash of the trimmed content and checks
it against `documents.content_hash`. If identical content already exists — regardless of its `status` — the request is
rejected instead of re-chunking and re-embedding the same text.

```text
POST /api/documents  (content already ingested)
  → 409 Conflict
```

```json
{
  "detail": "Document with identical content already exists",
  "existing_document_id": 7
}
```

Double-submits, retried jobs, and re-imported files cost nothing instead of silently doubling storage and embedding
work. The check is on exact content, not semantic similarity: two documents with the same meaning but different wording
are distinct.

**Race-proof.** A database-level `UNIQUE` constraint on `content_hash` (migration
`add_unique_constraint_to_content_hash`) backs up the application check. If two identical requests both pass the in-app
`get_document_by_hash()` pre-check before either commits, Postgres rejects the second `INSERT` with an `IntegrityError`.
`create_document()` catches it and returns the same `409`, re-resolving `existing_document_id` against the row that
actually won.

### Document Metadata

`POST /api/documents` accepts an optional `metadata` field: any JSON object, stored verbatim in a `JSONB` column
(migration `add_metadata_to_documents`). The app neither validates its shape nor reads any key from it. Use it for
source URL, author, ingestion batch, ACL tags, or anything else. It can be queried directly in Postgres with `JSONB`
operators, though the API does not expose metadata filtering today.

**Why the Python attribute is `doc_metadata`.** On the `Document` model the column is declared as
`doc_metadata = Column("metadata", JSONB, nullable=True)`. The database column is `metadata`, but `metadata` is reserved
on every SQLAlchemy declarative model (`Base.metadata` holds the schema's `MetaData` object), so the Python attribute
must be named differently. The Pydantic schemas (`DocumentCreate`, `DocumentDetail`, `SearchResult`) mirror this with
`doc_metadata: Optional[dict] = Field(default=None, alias="metadata")` and
`model_config = ConfigDict(populate_by_name=True)`. The JSON wire format keeps the clean `"metadata"` key.

**Where it appears.** `metadata` is accepted on `POST /api/documents` and returned by `GET /api/documents/{id}` and
`GET /api/search`. It is **not** returned by the `202` creation response or the `GET /api/documents` list, because both
use the plain `DocumentResponse` schema. To confirm what was stored, fetch it with `GET /api/documents/{id}`.

**Tested.** Four tests in `tests/test_api.py` cover it: stored on create and read back, `null` when omitted, included in
search results, and a non-object value rejected with `422`. This guards the alias wiring against silent breakage.

### Search Result Caching

`GET /api/search` is backed by Redis. The cache key is an MD5 hash of the normalized query (lowercased, stripped) plus
`top_k`, so identical searches share one entry, even across clients.

| Outcome          | Behavior                                                                                                                                     |
|------------------|----------------------------------------------------------------------------------------------------------------------------------------------|
| **Cache hit**    | Served straight from Redis with `X-Cache: HIT`. No embedding call, no DB query.                                                              |
| **Cache miss**   | The query is embedded, pgvector runs, and the result is cached with a TTL (`search_cache_ttl`, default `60s`) with `X-Cache: MISS`.          |
| **Invalidation** | When a document finishes processing (`status="completed"`), all `search:query:*` keys are flushed, so new content is searchable immediately. |

This trades a small, bounded amount of staleness for avoiding repeated embedding inference on hot queries.

Redis is an optimization, not a dependency: if it is unreachable, searches still succeed as cache misses.
See [Search hardening](#search-hardening).

### Observability

#### Structured JSON logging

Logs are one JSON object per line, emitted by a custom `JsonProfileFormatter` (`app/core/logging.py`). Every line
carries at least `timestamp`, `level`, `logger_name`, `message`, and `request_id`. Anything passed via
`logger.info(..., extra={...})` is folded into the same object, so event-specific fields (`method`, `path`,
`status_code`, `duration_ms` for requests; `document_id`, `chunk_count`, `error` for background processing) appear
alongside the standard ones.

A completed background job:

```json
{
  "timestamp": "2026-07-21T14:00:00+00:00",
  "level": "INFO",
  "logger_name": "app.services.document_service",
  "message": "document_processing_completed",
  "request_id": "a1b2c3d4-...",
  "document_id": 42,
  "chunk_count": 6,
  "total_processing_time_ms": 812.4
}
```

#### Request tracing

Every request passes through `ProfilerAndExceptionMiddleware`:

- The `request_id` is read from the incoming `X-Request-ID` header, or generated (`uuid4`) if absent. It is stored in a
  `ContextVar` for the life of the request, so any downstream logger call can use it without threading it through
  function signatures.
- The response carries `X-Request-ID` and `X-Response-Time` (milliseconds) headers.
- Each request is logged as one structured line by the `profiler` logger with `event: "request_completed"`, `method`,
  `path`, `status_code`, and `duration_ms`.
- Unhandled exceptions are caught by a single `try/except Exception` around `call_next()` in `app/core/middleware.py`.
  The stack trace is logged and the client receives a `500` with
  `{"detail": "Internal Server Error", "request_id": "..."}`, never a raw traceback. Use the `request_id` to find the
  exact log line. There is no separate `@app.exception_handler` in `main.py`; the middleware is the only catch-all.

#### Background task logging

`process_document_background()` runs after the response has gone out, outside the request/response cycle the middleware
wraps. By then the middleware's `ContextVar` has been reset, and `request_id_ctx.get()` would raise `LookupError`.

So `documents.py` reads `request_id_ctx.get()` **before** calling `background_tasks.add_task(...)`, while the context is
still alive, and passes it in as an explicit `request_id` parameter. The task logs it via `extra={"request_id": ...}` on
all three of its events: `document_processing_started`, `document_processing_completed` (with `chunk_count` and
`total_processing_time_ms`), and `document_processing_failed` (with `error`). Every background log line stays correlated
with the request that triggered it.

> **Not logged today: per-batch insert timing.** The chunk insert (`db.bulk_save_objects(chunks_to_insert)`) is not
> timed. Only `chunking_time_ms` and `embedding_time_ms` are persisted on the `Document` row, so an insert-latency
> regression would not show up in either field. If insert latency needs visibility, it needs its own timer and log line.

#### DB session handling — `get_db_context()`

Two call sites need a DB session outside FastAPI's `Depends(get_db)`: the background task in `document_service.py` and
the health checks in `system.py`. Both used to call `closing(next(get_db()))`. That only worked because `next()`
advances the generator to its `yield`, and nothing forces it to resume and run the commit/close code after it. It
happened to work because of when the generator was garbage-collected, which is not something to depend on.

`get_db_context()` (`app/database/db.py`) replaces that pattern. It is a plain `@contextlib.contextmanager` with the
same commit/rollback/close body. A `with get_db_context() as db:` block is **guaranteed** to run the code after `yield`
on exit, normally or via exception, because `contextlib` drives the generator through `__exit__`.

### Health Checks

Two endpoints under `/system`, split by purpose so orchestration and reverse-proxy checks target the right one.

#### `GET /system/live`

Liveness probe. Always returns `200` with `{"status": "alive"}` as long as the process can respond. It does **not**
touch the database, Redis, or the embedding model. It answers "is the process up?", never "is it working correctly?".

#### `GET /system/ready`

Readiness probe, validated against the `ReadinessResponse` schema. It checks three hard dependencies on every call:

- **`database`** — opens a fresh session via `get_db_context()` and runs `SELECT 1`.
- **`redis`** — sends a `PING`.
- **`embedding_model`** — runs a real embedding call (`get_embedding("healthcheck")`), so a model that failed to load or
  a broken inference path is caught, not just connectivity.

Each check returns `"ok"` or `"unreachable"`. An exception in any check is caught and logged; it never turns the health
endpoint itself into a `500`.

`200` — all dependencies healthy:

```json
{
  "status": "ready",
  "checks": {
    "database": "ok",
    "redis": "ok",
    "embedding_model": "ok"
  }
}
```

`503` — at least one dependency down:

```json
{
  "status": "unavailable",
  "checks": {
    "database": "unreachable",
    "redis": "ok",
    "embedding_model": "ok"
  }
}
```

The endpoint returns `503 Service Unavailable` unless **all** checks pass. This is what the `app` healthcheck in
`docker-compose.yml` polls (`curl -f http://localhost:8000/system/ready`) to decide when Nginx may start routing
traffic.

### Seeding Test Data

`scripts/populate_rag.py` inserts 50 sample documents (rotating across four topics) directly with `status="completed"`.
It uses the same `hash_content()`, chunking, and embedding services as the API, so seeded documents are immediately
searchable, with no waiting for background processing.

```bash
docker compose exec app python scripts/populate_rag.py
```

---

## API Reference

### `POST /api/documents`

Accepts a document and schedules chunking and embedding in the background. Returns immediately; it does **not** wait for
embedding to finish.

**Request**

```json
{
  "title": "FastAPI Guide",
  "content": "FastAPI is a modern...",
  "metadata": {
    "source": "docs.fastapi.tiangolo.com",
    "author": "tiangolo"
  }
}
```

`metadata` is optional and accepts any JSON object. It is stored as-is in a `JSONB` column and never validated or
interpreted. Omit it (or send `null`) and nothing is stored.

**Response `202 Accepted`**

```json
{
  "id": 1,
  "title": "FastAPI Guide",
  "status": "processing",
  "chunk_count": 0
}
```

> **Note:** the `202` response does not echo `metadata`. `DocumentResponse`, the schema behind this response and the
> `GET /api/documents` list, does not include the field. Use `GET /api/documents/{id}` to confirm what was stored.

**Response `409 Conflict`** — content already ingested (matched by SHA-256 hash;
see [Content Deduplication](#content-deduplication))

```json
{
  "detail": "Document with identical content already exists",
  "existing_document_id": 7
}
```

**Response `422 Unprocessable Entity`** — empty or whitespace-only `content`.

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
  "chunk_count": 4,
  "chunking_time_ms": 2.31,
  "embedding_time_ms": 148.92,
  "total_processing_time_ms": 151.23,
  "metadata": {
    "source": "docs.fastapi.tiangolo.com",
    "author": "tiangolo"
  }
}
```

`status` is one of `processing`, `completed`, or `failed`. While `processing`, `chunk_count` is `0` and the `*_time_ms`
fields are `null`. They are populated when background processing finishes, showing how much of the pipeline's latency
went to chunking versus embedding. `metadata` is the JSON object supplied at creation, or `null`.

---

### `GET /api/documents`

Lists documents with pagination. Each item includes `status` and `chunk_count`.

| Parameter | Type    | Default | Description       |
|-----------|---------|---------|-------------------|
| `limit`   | integer | `10`    | Page size (1–100) |
| `offset`  | integer | `0`     | Pagination offset |

---

### `GET /api/search`

Semantic search over stored chunks. Only chunks belonging to `completed` documents are searched. Results are cached in
Redis (see [Search Result Caching](#search-result-caching)), and the response carries an `X-Cache: HIT` or
`X-Cache: MISS` header.

**Query parameters**

| Parameter | Type    | Default  | Description                                                                   |
|-----------|---------|----------|-------------------------------------------------------------------------------|
| `q`       | string  | required | Search query, minimum 2 characters after trimming leading/trailing whitespace |
| `top_k`   | integer | `5`      | Number of results to return                                                   |

**Response `200`**

```json
[
  {
    "chunk_id": 3,
    "document_title": "FastAPI Guide",
    "content": "FastAPI is a modern web framework...",
    "score": 0.12,
    "metadata": {
      "source": "docs.fastapi.tiangolo.com",
      "author": "tiangolo"
    }
  }
]
```

> `metadata` is the *parent document's* metadata, carried through the `Chunk`↔`Document` join. Every chunk from the same
> document repeats it; it is not per-chunk.

> `score` is `1 - cosine_distance` (see `calculate_cosine_score` in `app/services/search_service.py`), so **a higher
score means higher similarity**. Results are ordered by ascending cosine distance from pgvector, which is the same as
> descending `score`. The first result is always the best match.

#### Search hardening

Four guarantees on `GET /api/search`, each backed by code and a test.

**1. Input validation: `q` needs at least 2 characters after normalization.**

`q` is normalized once at the start of the handler with `strip().lower()`. The normalized value must contain at least 2
characters; otherwise the handler raises `422`. Values shorter than 2 characters after normalization never reach Redis,
embedding, or the DB.

For example, `GET /api/search?q=  A  ` is rejected because the normalized value is `"a"`. A query such as
`GET /api/search?q=  Hello  ` is normalized to `"hello"` and the same canonical value is used for the cache key and
embedding.

Test: `test_if_min_length_works`, `test_search_normalizes_query`.

**2. Redis is optional: a cache outage never fails a search.**

Redis is touched twice per uncached request, and each touch is wrapped separately:

- **Read fails** (`ConnectionError` or `TimeoutError` on `get`, or invalid JSON in the cached value:
  `json.JSONDecodeError`): logged at `ERROR` as `READ_FAILED`, the response gets
  `X-Cache: MISS`, and the request carries on like a normal miss: embed the query, run pgvector, return `200` with fresh
  results.
- **Write fails** (`ConnectionError` or `TimeoutError` on `set`): logged at `WARNING` as `WRITE_FAILED`, swallowed, and
  the computed results are returned unchanged.

With Redis fully down, both happen in the same request: one `READ_FAILED` (`ERROR`), then one `WRITE_FAILED`
(`WARNING`), with the same `request_id`, status `200`, and `X-Cache: MISS`. Verified by running the real `search()`
against a Redis client pointed at a closed port.

Test: `test_search_handles_redis_unavailable`.

**3. `cache_status`: one structured log record per cache outcome.**

Emitted by `app/api/search.py` through the `redis_status` logger (message `cache_status`, extra fields `cache_status`
and `cache_key`; `request_id` is added by the log filter). Filter on `"logger_name": "redis_status"` in the JSON stdout
logs.

| Value          | Level     | Meaning                                                    | `X-Cache` header |
|----------------|-----------|------------------------------------------------------------|------------------|
| `HIT`          | `INFO`    | Result served from Redis                                   | `HIT`            |
| `MISS`         | `INFO`    | Key not in Redis, computed from the database               | `MISS`           |
| `READ_FAILED`  | `ERROR`   | Redis unreachable or timed out on `get`; treated as a miss | `MISS`           |
| `WRITE_FAILED` | `WARNING` | Redis failed or timed out on `set`; result not cached      | `MISS`           |

The header distinguishes only `HIT` from `MISS`; the two failure states exist only in the logs. Real records from a run
with Redis down (`timestamp` omitted for brevity):

```json
{
  "level": "ERROR",
  "logger_name": "redis_status",
  "message": "cache_status",
  "request_id": "1d8786ed-47cc-43cf-97d2-b33986fbf764",
  "cache_status": "READ_FAILED",
  "cache_key": "search:query:2abf71b1f72c25e360a97be01dc70fc5"
}
```

```json
{
  "level": "WARNING",
  "logger_name": "redis_status",
  "message": "cache_status",
  "request_id": "1d8786ed-47cc-43cf-97d2-b33986fbf764",
  "cache_status": "WRITE_FAILED",
  "cache_key": "search:query:2abf71b1f72c25e360a97be01dc70fc5"
}
```

`READ_FAILED` and `WRITE_FAILED` are separate so a log query tells you *which stage* of caching broke.

Tests: `test_search_handles_redis_hit`, `test_search_handles_redis_miss`, `test_search_handles_redis_unavailable`.

**4. Async-safe: the handler does not block the event loop.**

`search()` is `async def`, but `redis_client.get`, `redis_client.set`, and the SQLAlchemy `db.query(...).all()` are
synchronous (`redis-py` and a sync `Session`). Called directly, they hold the event-loop thread while waiting on Redis
or PostgreSQL and stall every other request on that worker. All three are wrapped in `run_in_threadpool` (embedding
already was, via `embedding_service.py`).

Proof: `test_search_endpoint_does_not_block_event_loop` fires 3 concurrent requests against fakes that `time.sleep(1)`
in `get`, in `set`, and in the DB query (3 s per request), and asserts the whole batch finishes in under 4 s.

- About **3 s** is what the threaded version should take, and about **9 s** (3 requests × 3 s) is what it would take if
  every call blocked the loop. Both are *calculated* from the fakes' `sleep` values, not measured.
- The *measured* negative control: with only `redis_client.set()` left unwrapped, the same test took **5.03 s**, above
  the 4 s threshold.

---

### `DELETE /api/documents/{id}`

Deletes a document and its chunks (cascade). Returns `204` on success, `404` if not found.

---

### `GET /system/live` and `GET /system/ready`

Liveness and readiness probes. See [Health Checks](#health-checks) for the full breakdown.

---

## Project Structure

```text
rag-api/
├── app/
│   ├── api/
│   │   ├── documents.py          # POST/GET/DELETE /api/documents, background task trigger, dedup check
│   │   ├── search.py             # GET /api/search (Redis cache, filters status="completed")
│   │   └── system.py             # GET /system/live, /system/ready (DB, Redis, embedding model checks)
│   ├── core/
│   │   ├── context.py            # ContextVar carrying the current request_id
│   │   ├── middleware.py         # Request timing, request-id tagging, catch-all error handling
│   │   ├── logging.py            # "profiler" logger config, injects request_id into log lines
│   │   └── redis.py              # Cached Redis client factory
│   ├── database/
│   │   ├── models.py             # Document (status, content_hash, timing metrics, doc_metadata/JSONB), Chunk
│   │   ├── db.py                 # Session management
│   │   └── base.py               # Declarative base
│   ├── services/
│   │   ├── document_service.py   # CRUD, hash_content/get_document_by_hash, background processing, cache invalidation
│   │   ├── embedding_service.py  # sentence-transformers wrapper (runs off the event loop via threadpool)
│   │   ├── chunking_service.py   # Fixed-size overlapping text chunking
│   │   └── search_service.py     # Cosine distance → similarity score conversion
│   ├── schemas.py                # Pydantic request/response models (incl. ReadinessResponse, metadata alias)
│   ├── config.py                 # Pydantic settings (DB, Redis, cache TTL)
│   └── main.py                   # FastAPI app, router registration
├── alembic/                      # Migrations (status, HNSW index, content_hash + metrics, unique constraint, metadata)
├── tests/                        # Pytest suite (47 tests)
├── docker-compose.yml            # Production stack (app + Postgres/pgvector + Redis + Nginx)
├── docker-compose.test.yml       # Isolated test stack (Postgres + Redis containers)
├── Dockerfile                    # Multi-stage, non-root
└── nginx.conf                    # Per-route rate limiting, proxy config
```

> `process_document_background()` lives in `app/services/document_service.py`. `app/api/documents.py` only wires it into
> the route via `BackgroundTasks`.

---

## Running Tests

Tests run against isolated PostgreSQL and Redis containers, with `tmpfs` for Postgres: no persistent data, no side
effects.

```bash
docker compose -f docker-compose.test.yml up --build --abort-on-container-exit
```

**47 tests** cover:

- **Async lifecycle** — immediate `202`/`processing` response; `completed` status with the correct `chunk_count` and
  populated `*_time_ms` fields once processing finishes; a mocked failure landing on `status="failed"`; search excluding
  chunks from non-`completed` documents.
- **Deduplication** — duplicate content against a `completed` document returns `409`; so does duplicate content against
  a still-`processing` document; genuinely different content is always accepted; the stored `content_hash` matches an
  independently computed hash; a simulated race (both requests pass the Python-level pre-check) is still caught by the
  database `UNIQUE` constraint and turned into a `409`.
- **Search caching** — repeated identical queries hit the cache; a new query misses; different `top_k` values produce
  different cache keys; the cache is invalidated once a document finishes processing.
- **Search hardening** — a 1-character `q` returns `422`; with Redis unavailable or timing out on read, search still
  returns `200` with `X-Cache: MISS` and a `READ_FAILED` record; `HIT` and `MISS` records are emitted on the matching
  paths; three concurrent requests against artificially slow (`time.sleep`) Redis and DB fakes finish in under 4 s,
  proving `search()` does not block the event loop.
- **Document metadata** — stored on create and returned by `GET /api/documents/{id}`; `null` when omitted; included in
  `GET /api/search` results; a non-object value rejected with `422`.
- **Health checks** — `/system/live` always returns `200`. `/system/ready` returns `200` when the database, Redis, and
  embedding model all check out, and `503` when any single one fails. The per-check breakdown is verified in both the
  healthy and unhealthy response bodies.
- **CRUD / validation / error handling** — listing, fetching, and deleting documents (including `404`s); empty and
  whitespace-only content rejection (`422`); score ordering; the response shape of the catch-all exception middleware.
- **Structured logging** — the JSON formatter emits valid JSON with all required fields; a background job's log lines
  carry the same `request_id` as the triggering request's response header; a failed document's log line contains the
  `error` field.
- **DB session handling** — `get_db_context()` commits and closes on the happy path, and rolls back and closes when the
  block raises.
- **`populate_rag.py`** — running the script against a clean database produces `completed` documents that are
  immediately visible in `GET /api/search`.

---

## Environment Variables

See `.env.example` for every required variable. The most relevant ones beyond standard Postgres and app settings:

| Variable                             | Used by                              | Default                             | Notes                                                                                       |
|--------------------------------------|--------------------------------------|-------------------------------------|---------------------------------------------------------------------------------------------|
| `REDIS_URL`                          | `app/config.py` → `redis_url`        | `redis://redis:6379/0`              | Backs both search caching and cache invalidation.                                           |
| `SEARCH_CACHE_TTL`                   | `app/config.py` → `search_cache_ttl` | `60` (seconds)                      | Set in `.env.example`; override it in your own `.env` for a different TTL.                  |
| `DATABASE_URL` / `TEST_DATABASE_URL` | `app/config.py`                      | Required                            | Full SQLAlchemy connection strings. `TEST_DATABASE_URL` is used by the isolated test stack. |
| `APP_TITLE`                          | `app/config.py` → `app_title`        | Required (no default in `Settings`) | Used as the FastAPI app title, shown in Swagger UI at `/docs`.                              |

---

## Engineering Decisions

### pgvector over a dedicated vector DB (Pinecone, Weaviate)

At this scale, PostgreSQL + pgvector removes the operational overhead of running a separate service, and the HNSW index
keeps search fast. A dedicated vector database becomes worthwhile at around 10M+ vectors or when multi-tenancy grows
complex.

### Local sentence-transformers over OpenAI embeddings

Zero API cost, zero external dependency, fully reproducible results. `all-MiniLM-L6-v2` produces 384-dimensional
embeddings, smaller and faster than the 1536-dimensional vectors of OpenAI's `text-embedding-ada-002`, with strong
retrieval quality for English.

### HNSW index over IVFFlat

HNSW builds incrementally and works on an empty table. IVFFlat builds its clusters from existing data, so it needs a
populated table, and it requires re-indexing and a `VACUUM ANALYZE` after bulk inserts. HNSW uses more memory but
delivers better query-time performance and simpler operational behavior.

### `BackgroundTasks` over Celery, for now

`BackgroundTasks` runs in-process, in the same event loop, after the response is sent. For CPU-bound work like
`sentence-transformers` inference, the embedding call occupies the worker, and other requests hitting the same Gunicorn
worker queue behind it until embedding finishes.

This is mitigated today by `run_in_threadpool` inside `embedding_service.py`, which moves the blocking call off the main
event-loop thread. But it is still bounded by the same process's thread pool, so it is not truly isolated.

A real task queue (Celery/RQ + Redis or RabbitMQ) runs work in separate processes. A burst of slow embedding jobs can't
starve API request handling, and jobs survive a process restart.

- **Today:** `BackgroundTasks` is the right call to get unblocked.
- **Later:** move to Celery once ingestion volume or embedding latency grows to the point where a single failed deploy
  must not be allowed to drop in-flight jobs.

### Batch insert (`bulk_save_objects`) over per-chunk `INSERT`

Chunks are inserted with a single `db.bulk_save_objects(chunks_to_insert)` and one `commit()`: one network round trip to
Postgres regardless of chunk count, instead of N. The difference is negligible for a handful of chunks but compounds
with document length. Insert time is not measured separately (see [Observability](#observability)). It is worth adding
if chunk counts grow enough that insert latency needs visibility distinct from `chunking_time_ms` and
`embedding_time_ms`.

### An explicit `status` column instead of inferring state from `chunk_count`

`chunk_count == 0` is ambiguous. It is true for a document that has not started processing, for one that failed
immediately (for example, chunking threw before any chunk was created), and for an empty or degenerate document that
legitimately produces zero chunks after `completed` processing.

An explicit `status` column removes the guesswork, and the race where a client polling on `chunk_count > 0` reports
`completed` prematurely. That happens when it catches the document between chunk-row inserts, for example after 2 of 4
chunks were committed but before the final `status="completed"` update lands.

### A fresh DB session for background tasks

The `Depends(get_db)` session is scoped to the request lifecycle. By the time a `BackgroundTasks` callback runs, the
response has been returned and that generator-based session is on its way to being torn down. Reusing it would mean
operating on a session that may already be closed, mid-rollback, or recycled by SQLAlchemy's pool for an unrelated
request.

The background function opens its own session via `get_db_context()`
(see [DB session handling](#db-session-handling--get_db_context)), a `@contextlib.contextmanager` independent of any
request, and is responsible for its own `commit` and `rollback`. An earlier version used `closing(next(get_db()))`; that
pattern is gone.

### A real `UNIQUE` constraint on top of the application-level dedup check

The `get_document_by_hash()` pre-check in `create_document()` handles the common case cheaply (no constraint violation,
no exception path). But it cannot see an in-flight, uncommitted insert from a concurrent request. That is a genuine
TOCTOU race under any real concurrent load.

The `UNIQUE` constraint on `documents.content_hash` (`add_unique_constraint_to_content_hash`) is the actual source of
truth. Whichever request commits second is rejected by Postgres with an `IntegrityError`, which is caught and converted
to the same `409` shape the pre-check returns.

---

## Author

**Vladislav** — Backend Engineering · AI Systems · Vector Search