import hashlib
import json

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.config import settings
from app.core.redis import get_redis_client
from app.database.db import get_db
from app.database.models import Document, Chunk
from app.schemas import SearchResult
from app.services.embedding_service import get_embedding
from app.services.search_service import calculate_cosine_score

router = APIRouter()


@router.get("", response_model=list[SearchResult])
async def search(
        response: Response,
        q: str,
        top_k: int = 5,
        db: Session = Depends(get_db)
):
    query_hash = hashlib.md5(f"{q.strip().lower()}:{top_k}".encode("utf-8")).hexdigest()
    cache_key = f"search:query:{query_hash}"

    redis_client = get_redis_client()

    cached_data = redis_client.get(cache_key)
    if cached_data:
        response.headers["X-Cache"] = "HIT"
        return json.loads(cached_data)

    response.headers["X-Cache"] = "MISS"

    vector = await get_embedding(q)
    distance = Chunk.embedding.cosine_distance(vector)
    results = (
        db.query(Chunk, Document.title, distance.label("distance"))
        .join(Document, Chunk.document_id == Document.id)
        .filter(Document.status == "completed")
        .order_by(distance)
        .limit(top_k)
        .all()
    )

    formatted_results = [
        {
            "chunk_id": row.Chunk.id,
            "document_title": row.title,
            "content": row.Chunk.content,
            "score": calculate_cosine_score(row.distance)
        }
        for row in results
    ]

    redis_client.set(
        cache_key,
        json.dumps(formatted_results, ensure_ascii=False),
        ex=settings.search_cache_ttl
    )

    return formatted_results
