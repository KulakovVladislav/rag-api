from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database.db import get_db
from app.database.models import Document, Chunk
from app.schemas import SearchResult
from app.services.embedding_service import get_embedding
from app.services.search_service import calculate_cosine_score

router = APIRouter()


@router.get("", response_model=list[SearchResult])
async def search(q: str, top_k: int = 5, db: Session = Depends(get_db)):
    vector = await get_embedding(q)
    distance = Chunk.embedding.cosine_distance(vector)
    results = (
        db.query(Chunk, Document.title, distance.label("distance"))
        .join(Document, Chunk.document_id == Document.id)
        .order_by(distance)
        .limit(top_k)
        .all()
    )
    search_results = [
        {
            "chunk_id": row.Chunk.id,
            "document_title": row.title,
            "content": row.Chunk.content,
            "score": calculate_cosine_score(row.distance)
        }
        for row in results
    ]
    search_results.sort(key=lambda x: x["score"], reverse=True)
    return search_results