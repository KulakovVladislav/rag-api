# Search, Redis, Validation, and Event Loop Findings

## Query Validation

Set `min_length=2` for the `q` query parameter.

**Reason:** This enforces a minimum level of meaningful input for semantic search. It prevents meaningless one-character
queries while still allowing valid short abbreviations.

---

## Redis Error Handling

Catch `redis.exceptions.ConnectionError`.

**Reason:** `ConnectionError` is specifically designed to handle failures caused by an unavailable or unexpectedly
disconnected Redis service.

---

## Cache Status Logging

Add a `cache_status` field to the `search()` logs.

### Field

`cache_status`

### Possible values

* `HIT` — cached result was successfully retrieved.
* `MISS` — no cached result was found.
* `READ_FAILED` — an error occurred while reading from Redis.
* `WRITE_FAILED` — an error occurred while writing to Redis.

### Why Read and Write Failures Are Separated

Separating `READ_FAILED` and `WRITE_FAILED` makes logs more informative and allows us to identify exactly which stage of
the caching process failed. This makes debugging and monitoring easier.

---

## Cache Write After Database Query

If the requested result is not available in Redis, retrieve the data from the database and attempt to store the result
in Redis using `set()`.

This allows subsequent identical search requests to be served from the cache.

---

## Test Isolation

Patch the Redis factory function and clear the cache before each test.

Using the factory function instead of patching an already-created client prevents tests from sharing the same Redis
client state and potentially affecting one another.

The goal is to keep each test isolated and deterministic.

---

## Redis Unavailability Test

An error occurred in the Redis-unavailability test:

```text
any(record.cache_status == ...)
```

raised an `AttributeError` for log records that did not contain the `cache_status` attribute.

Some records, such as `profiler` and `httpx2` logs, do not define this field.

### Why This Happened

`any()` evaluates its condition for each item in the iterable until it finds a truthy result. It does not automatically
ignore exceptions raised while evaluating the condition.

Therefore, accessing:

```python
record.cache_status
```

raises `AttributeError` when the current record does not contain that attribute.

### Solution

Use:

```python
getattr(record, "cache_status", None)
```

This safely returns `None` when the attribute does not exist. The comparison then evaluates to `False` instead of
raising an exception.

---

# Blocking Operations Inside `async def search()`

Two synchronous blocking operations were identified inside `async def search()`.

Both execute without `await` and without a threadpool wrapper.

## 1. Synchronous Redis Operations

```python
redis_client.get(cache_key)
redis_client.set(...)
```

The Redis client is created using:

```python
redis.from_url(...)
```

This uses the standard synchronous `redis-py` client rather than `redis.asyncio`. Therefore, `.get()` and `.set()` are
synchronous methods and cannot be awaited.

These operations perform blocking network I/O to Redis. While waiting for a Redis response, the event-loop thread
remains occupied and cannot execute other coroutines.

---

## 2. Synchronous SQLAlchemy Query

```python
db.query(
    Chunk,
    Document.title,
    ...
).all()
```

The database session is created through `SessionLocal()` in:

```text
app/database/db.py
```

This is a standard synchronous SQLAlchemy `Session`, not an `AsyncSession`.

Therefore:

```python
.query(...).all()
```

performs synchronous database I/O without `await` and without a threadpool wrapper.

While waiting for PostgreSQL to respond, the event-loop thread remains blocked and cannot process other coroutines.

---

## Non-Blocking Comparison: Embedding Generation

The following operation inside `search()` is already handled correctly:

```python
get_embedding(q)
```

`embedding_service.py` wraps the CPU-bound model execution (`generate_embeddings_sync`) with:

```python
await run_in_threadpool(...)
```

This moves the blocking CPU-bound operation to a separate thread and allows the event loop to continue processing other
asynchronous tasks while the operation is running.

---

# Why These Operations Are Blocking

The issue is not simply that these operations may be slow.

The critical issue is that they are **synchronous operations executed directly on the event-loop thread**. Because they
do not yield control back to the event loop, other coroutines cannot execute while these operations are in progress.

In other words:

* `redis_client.get()` blocks the event loop while waiting for Redis.
* `redis_client.set()` blocks the event loop while writing to Redis.
* `db.query(...).all()` blocks the event loop while waiting for PostgreSQL.
* `await run_in_threadpool(...)` does not block the event loop because the blocking work is executed in a separate
  thread.

The architectural requirement is therefore:

> Synchronous I/O or CPU-bound operations must not be executed directly inside an `async def` request handler when they
> can block the event-loop thread.

# Architectural Decision Record: Testing Concurrency and Latency with Module-Level Imports

## Context

Our FastAPI RAG application isolates slow synchronous I/O operations (Database queries and Redis caching) using
Starlette's `run_in_threadpool`. To ensure that these operations run asynchronously in background threads and do not
freeze the main Event Loop, we need automated concurrency testing with injected latency.

However, while the database session (`db`) is injected per-request using FastAPI's `Depends`, the `redis_client` is
initialized globally at the module level (`app/api/search.py`) via `redis.from_url(...)` and imported directly. This
prevents us from using FastAPI's native `app.dependency_overrides` for Redis.

## Decision

We will use a **Hybrid Isolation Strategy**:

1. **Database:** Standard `app.dependency_overrides` to inject a simulated `FakeSlowDatabase`.
2. **Redis:** Module-level mocking using `unittest.mock.patch` (or pytest's `monkeypatch`) targeting the specific import
   path `app.api.search.redis_client`.

Both fakes will implement synchronous `time.sleep()` to rigorously simulate the blocking behavior of real networking
drivers, verifying that `run_in_threadpool` prevents Event Loop degradation.

Additionally, our execution mechanics dictate that:

* The factory method `get_redis_client` is mocked at the function level rather than an object instance to accommodate
  runtime evaluation in the route body.
* The `get_embedding` helper method is also systematically intercepted and stubbed to avoid hitting third-party vector
  dependencies during execution.
* A base delay of 1.0s alongside an overall test threshold of 4.0s are established via negative control metrics
  (verifying async threadpool concurrency at 3.1s versus sequential block failure scaling to 5.03s).

## Trade-offs of the Hybrid Approach

### Pros

* **Complete Test Coverage:** Safely validates both the DB thread scheduling and Redis thread scheduling inside the
  actual HTTP endpoint pipeline.
* **Zero Production Code Changes:** We do not need to rewrite stable production code or force `Depends(get_redis)` onto
  the codebase solely to satisfy a test framework.
* **High Controllability:** Synchronous `time.sleep()` within the isolated thread mimics real network lag perfectly
  without breaking the test runner's execution queue.

### Cons

* **Brittle Import Paths:** Using `mock.patch` requires hardcoding the exact string path where `redis_client` is
  consumed (`app.api.search.redis_client`). If the file structure or internal imports change, the test will silently
  fail to intercept the client.
* **Global State Risks:** Modifying module-level attributes can pollute other tests if the patch is not carefully torn
  down or scoped properly within pytest fixtures.

# Architectural Decision Record: How CI Receives `.env`

## Context

`ci.yml` did not create a `.env` file, while the `test-runner` service requires one through `env_file`; without it,
Docker Compose fails before any container starts. The `.env` file is ignored by Git and the CI runner performs a clean
checkout, so the file is not present, while the test runner only actually takes `app_title` from it because the
remaining values are overridden by `environment` in `docker-compose.test.yml`.

## Options considered

1. **Commit `.env` to the repository.** This conflicts with the repository's `.gitignore` policy and standard security
   practices for environment configuration.
2. **Create `.env` in the workflow.** The workflow can create the required file from the committed `.env.example` before
   starting Docker Compose.
3. **Remove the dependency on `.env`.** This could be done either by removing `env_file` and duplicating the
   configuration in two places, or by using `required: false`, which requires Compose 2.24.0 or newer and produces a
   hard failure on older Compose versions.

## Decision

CI will create the required file with `cp .env.example .env`, because copying keeps the CI configuration derived from
the single committed template instead of manually maintaining a second list of environment-variable assignments. A
manually constructed list would have to be updated whenever a field in `Settings` changes, creating an avoidable drift
risk.

## Trade-offs

This keeps secrets out of Git and makes CI depend on `.env.example` remaining valid, while still requiring a workflow
step before Compose starts. Local development and CI now obtain `.env` through different mechanisms: developers create
it manually, while CI copies `.env.example`.

The rejected alternatives would either duplicate configuration or impose a Compose-version dependency. Manual
string-by-string construction would add ongoing maintenance cost because every `Settings` change would require another
CI configuration update.

* **Dual-Purpose Validation for `.env.example`:** Every CI run now exercises the committed `.env.example`; if a required
  value used by the test runner is missing or invalid, the CI pipeline can fail. This validation is limited to
  configuration that is not overridden by `environment` in `docker-compose.test.yml`; currently, that means `APP_TITLE`.
* **Divergent Configuration Mechanics:** Local development and the CI runner use separate configuration flows.
  Developers still create and manage their `.env` files manually on their workstations, while CI dynamically creates its
  `.env` with `cp .env.example .env`.
