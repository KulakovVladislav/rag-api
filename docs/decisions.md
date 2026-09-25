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

This uses the standard synchronous `redis-py` client rather than `redis.asyncio`.

Therefore, `.get()` and `.set()` are synchronous methods and cannot be awaited.

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

The critical issue is that they are **synchronous operations executed directly on the event-loop thread**.

Because they do not yield control back to the event loop, other coroutines cannot execute while these operations are in
progress.

In other words:

* `redis_client.get()` blocks the event loop while waiting for Redis.
* `redis_client.set()` blocks the event loop while writing to Redis.
* `db.query(...).all()` blocks the event loop while waiting for PostgreSQL.
* `await run_in_threadpool(...)` does not block the event loop because the blocking work is executed in a separate
  thread.

The architectural requirement is therefore:

> Synchronous I/O or CPU-bound operations must not be executed directly inside an `async def` request handler when they
> can block the event-loop thread.
