from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database.db import get_db
from app.database.models import Document, Chunk
from app.services.embedding_service import get_embedding

router = APIRouter()


class SearchResult(BaseModel):
    chunk_id: int
    document_title: str
    content: str
    score: float


@router.get("", response_model=list[SearchResult])
async def search(q: str, top_k: int = 5, db: Session = Depends(get_db)):
    vector = await get_embedding(q)
    distance = Chunk.embedding.cosine_distance(vector)
    results = (
        db.query(Chunk, Document.title, distance.label("score"))
        .join(Document, Chunk.document_id == Document.id)
        .order_by(distance)
        .limit(top_k)
        .all()
    )
    return [
        {
            "chunk_id": row.Chunk.id,
            "document_title": row.title,
            "content": row.Chunk.content,
            "score": row.score
        }
        for row in results
    ]
