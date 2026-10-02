# Decisions

The choices behind search, caching, testing, and CI — and what each one costs.

Every entry follows the same shape: **Context** (why it came up), **Options** (what we weighed), **Decision** (what we
chose), **Cost** (what we accepted).

## Contents

- [Search](#search)
- [Redis resilience](#redis-resilience)
- [Concurrency](#concurrency)
- [Testing](#testing)
- [CI](#ci)

---

## Search

### Query validation

**Decision.** `q` requires at least 2 characters: `min_length=2`.

**Why.** Semantic search needs a minimum of meaningful input. Two characters rule out one-character noise and still
allow short abbreviations such as `ab`.

**Cost.** Length is checked on the raw string, so a query of two spaces passes.

### Write the cache after the database

**Decision.** On a cache miss, read from the database, then store the result in Redis with `set()`.

**Why.** The next identical request is served from the cache.

---

## Redis resilience

Redis is an optimization, not a dependency. A cache outage must never fail a search.

### 1. What the read path catches

**Context.** The first version caught only `redis.exceptions.ConnectionError`, which covers an unavailable or
disconnected Redis. A `TimeoutError` is a separate exception class in `redis-py`, so it escaped to the catch-all
middleware and became a `500`. This decision supersedes the earlier `ConnectionError`-only choice.

**Options.**

| Option                            | Verdict                                                                                                      |
|-----------------------------------|--------------------------------------------------------------------------------------------------------------|
| `Exception`                       | Too broad. It would hide unrelated bugs — a `json.loads` failure, for example, would pass as a quiet `MISS`. |
| `redis.exceptions.RedisError`     | Wider than necessary.                                                                                        |
| `(ConnectionError, TimeoutError)` | Exactly the two failures that mean "Redis is not answering".                                                 |

**Decision.** Catch the tuple `(redis.exceptions.ConnectionError, redis.exceptions.TimeoutError)`.

**Cost.** Degradation is not instant. With `redis-py` 8.0.0 defaults, `socket_timeout` is 5 seconds, so a `get` against
an unresponsive Redis can hold the request for up to 5 seconds before it falls back to the database. The same release
also changed the default retry behavior (its release notes describe 10 attempts with exponential jitter backoff).
Whether that stacks extra waiting on top of a read timeout depends on `retry_on_timeout`, which the client docs list as
`False` by default, and on how our client is created. Treat 5 seconds as the per-attempt figure and measure the real
worst case before quoting a total.

### 2. Read and write use the same exceptions

**Decision.** The read path catches the same set as the write path.

**Behavior.** If `set` times out after a successful database read, the client still gets `200` with results. The log
carries `WRITE_FAILED` at `WARNING`.

**Why.** One rule for both directions is easier to reason about and to test.

### 3. `cache_status` and log levels

**Context.** One structured field on every `search()` log record shows what the cache did.

**Decision.**

| `cache_status` | Level     | Meaning                        |
|----------------|-----------|--------------------------------|
| `HIT`          | `INFO`    | A cached result was retrieved. |
| `MISS`         | `INFO`    | No cached result was found.    |
| `READ_FAILED`  | `ERROR`   | Reading from Redis failed.     |
| `WRITE_FAILED` | `WARNING` | Writing to Redis failed.       |

A timeout on read is `READ_FAILED` at `ERROR`, the same as a connection error.

**Why separate read and write failures.** The logs show exactly which stage of caching broke, which makes debugging and
monitoring easier.

**Cost.** By status alone, a timeout and a dropped connection look the same. The exception class can be added to `extra`
to tell them apart. That is optional and not planned for now.

---

## Concurrency

### Blocking calls inside `async def search()`

**Context.** Two synchronous operations ran directly on the event-loop thread, with no `await` and no threadpool
wrapper.

| Operation                                    | Why it blocks                                                                                                                                                          |
|----------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `redis_client.get(...)` / `.set(...)`        | The client comes from `redis.from_url(...)`, the standard synchronous `redis-py` client, not `redis.asyncio`. Each call waits on network I/O while holding the thread. |
| `db.query(Chunk, Document.title, ...).all()` | The session comes from `SessionLocal()` in `app/database/db.py`: a synchronous `Session`, not an `AsyncSession`. It waits on PostgreSQL while holding the thread.      |

The embedding call, `get_embedding(q)`, was already correct. `embedding_service.py` runs the CPU-bound
`generate_embeddings_sync` through `await run_in_threadpool(...)`.

**The real problem.** Slowness alone is not the issue. These calls run on the event-loop thread and never hand control
back, so no other coroutine can run until they finish. `run_in_threadpool` moves the wait onto a separate thread, and
the loop keeps working.

**Decision.** Synchronous I/O and CPU-bound work must not run directly inside an `async def` request handler. Wrap Redis
calls and the database query in `run_in_threadpool`.

---

## Testing

### Test isolation

**Decision.** Patch the Redis factory function and clear the cache before each test.

**Why.** Patching the factory, rather than an already-created client, stops tests from sharing client state. Each test
stays isolated and deterministic.

### Reading log records safely

**Context.** The Redis-unavailability test failed with an `AttributeError`:

```python
any(record.cache_status == ...)
```

Records from other loggers, such as `profiler` and `httpx2`, have no `cache_status` attribute. `any()` stops at the
first truthy result, but it does not ignore exceptions raised while evaluating each item, so the first record without
the attribute raised.

**Decision.** Read the attribute with a default:

```python
getattr(record, "cache_status", None)
```

A missing attribute becomes `None`, the comparison is `False`, and nothing is raised.

### Testing concurrency with module-level imports

**Context.** The application isolates slow synchronous I/O with Starlette's `run_in_threadpool`. To prove that the event
loop stays free, the tests inject latency. The database session is injected per request through `Depends`, so FastAPI's
`app.dependency_overrides` works. The Redis client is created at module level in `app/api/search.py` through
`redis.from_url(...)` and imported directly, so `dependency_overrides` cannot reach it.

**Decision.** A hybrid strategy:

1. **Database.** Use `app.dependency_overrides` to inject a `FakeSlowDatabase`.
2. **Redis.** Use `unittest.mock.patch` (or `monkeypatch`) on the import path `app.api.search.redis_client`.

Both fakes call a synchronous `time.sleep()`, which imitates a blocking network driver. If `run_in_threadpool` works,
the event loop stays responsive.

**How it runs.**

- The factory `get_redis_client` is mocked at the function level rather than on an instance, because it is evaluated at
  runtime in the route body.
- `get_embedding` is stubbed, so tests never touch third-party vector dependencies.
- Each fake sleeps 1.0 s, and the pass threshold for the whole test is 4.0 s. As a negative control, the threaded
  version finishes in about 3.1 s, while a blocked version scales to 5.03 s.

**Benefits.**

- Covers both database and Redis thread scheduling inside the real HTTP pipeline.
- Needs no production code changes, such as forcing `Depends(get_redis)` just for tests.
- `time.sleep()` in an isolated thread imitates real network lag without stalling the test runner.

**Cost.**

- **Brittle import path.** `mock.patch` needs the exact string `app.api.search.redis_client`. If files or imports move,
  the patch can silently stop intercepting the client.
- **Global state.** Patching module-level attributes can leak into other tests unless the patch is scoped and torn down
  inside a pytest fixture.

---

## CI

### How CI receives `.env`

**Context.** `ci.yml` never created a `.env` file, but the `test-runner` service requires one through `env_file`.
Without it, Docker Compose fails before any container starts. `.env` is ignored by Git, and the CI runner does a clean
checkout, so the file is not there. The test runner takes only `APP_TITLE` from it; every other value is overridden by
`environment` in `docker-compose.test.yml`.

**Options.**

| Option                                            | Verdict                                                                                                                                                           |
|---------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Commit `.env` to the repository                   | Conflicts with `.gitignore` and with basic security practice for environment files.                                                                               |
| Create `.env` in the workflow from `.env.example` | Keeps CI derived from the one committed template.                                                                                                                 |
| Remove the dependency on `.env`                   | Either drop `env_file` and duplicate configuration in two places, or use `required: false`, which needs Compose 2.24.0 or newer and fails hard on older versions. |

**Decision.** CI runs `cp .env.example .env` before Compose starts.

**Why.** CI stays derived from a single template. A hand-built list of variables would need an update every time a field
in `Settings` changes, which is drift waiting to happen.

**Cost.**

- **A workflow step is still required** before Compose starts, and CI now depends on `.env.example` staying valid.
- **Two ways to get `.env`.** Developers create it by hand; CI copies the template.
- **Limited validation.** Every CI run now exercises the committed `.env.example`, and a missing or invalid value can
  fail the pipeline. That covers only configuration not overridden by `environment` in `docker-compose.test.yml` —
  today, `APP_TITLE`.