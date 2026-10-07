import hashlib
import json
import logging
import time

import redis
from fastapi import APIRouter, Depends, Response, HTTPException, status
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.core.redis import get_redis_client
from app.database.db import get_db
from app.database.models import Document, Chunk
from app.schemas import SearchResult
from app.services.embedding_service import get_embedding
from app.services.search_service import calculate_cosine_score

router = APIRouter()
logger = logging.getLogger("redis_status")


@router.get("", response_model=list[SearchResult])
async def search(
        response: Response,
        q: str,
        top_k: int = 5,
        db: Session = Depends(get_db)
):
    canon_q = q.strip().lower()
    if len(canon_q) < 2:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=[
                {
                    "type": "string_too_short",
                    "loc": ["query", "q"],
                    "msg": "String should have at least 2 characters after normalization",
                    "input": q,
                }
            ],
        )

    query_hash = hashlib.md5(f"{canon_q}:{top_k}".encode("utf-8")).hexdigest()
    cache_key = f"search:query:{query_hash}"

    redis_client = get_redis_client()
    redis_read_ms = None
    embedding_ms = None
    db_query_ms = None
    redis_write_ms = None
    try:
        try:
            redis_get_start_time = time.perf_counter()
            try:
                cached_data = await run_in_threadpool(redis_client.get, cache_key)
            finally:
                redis_read_ms = (time.perf_counter() - redis_get_start_time) * 1000
            if cached_data:
                logger.info("cache_status", extra={"cache_status": "HIT", "cache_key": cache_key})
                response.headers["X-Cache"] = "HIT"
                return json.loads(cached_data)
        except (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError, json.JSONDecodeError):
            logger.error("cache_status", extra={"cache_status": "READ_FAILED", "cache_key": cache_key})
            response.headers["X-Cache"] = "MISS"
        else:
            logger.info("cache_status", extra={"cache_status": "MISS", "cache_key": cache_key})
            response.headers["X-Cache"] = "MISS"

        embedding_start_time = time.perf_counter()
        try:
            vector = await get_embedding(canon_q)
        finally:
            embedding_ms = (time.perf_counter() - embedding_start_time) * 1000
        distance = Chunk.embedding.cosine_distance(vector)
        db_start_time = time.perf_counter()
        try:
            results = await run_in_threadpool(
                lambda: (
                    db.query(Chunk, Document.title, Document.doc_metadata, distance.label("distance"))
                    .join(Document, Chunk.document_id == Document.id)
                    .filter(Document.status == "completed")
                    .order_by(distance)
                    .limit(top_k)
                    .all()
                )
            )
        finally:
            db_query_ms = (time.perf_counter() - db_start_time) * 1000

        formatted_results = [
            {
                "chunk_id": row.Chunk.id,
                "document_title": row.title,
                "content": row.Chunk.content,
                "score": calculate_cosine_score(row.distance),
                "metadata": row.doc_metadata,
            }
            for row in results
        ]

        serialized_data = json.dumps(formatted_results, ensure_ascii=False)

        try:
            redis_write_start_time = time.perf_counter()
            try:
                await run_in_threadpool(
                    redis_client.set,
                    cache_key,
                    serialized_data,
                    ex=settings.search_cache_ttl
                )
            finally:
                redis_write_ms = (time.perf_counter() - redis_write_start_time) * 1000
        except (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError):
            logger.warning("cache_status", extra={"cache_status": "WRITE_FAILED", "cache_key": cache_key})
            pass

        return formatted_results
    finally:
        raw_metrics = {
            "redis_read_ms": redis_read_ms,
            "embedding_ms": embedding_ms,
            "db_query_ms": db_query_ms,
            "redis_write_ms": redis_write_ms,
        }

        metrics = {k: v for k, v in raw_metrics.items() if v is not None}

        logger.info("search_timing", extra=metrics)
