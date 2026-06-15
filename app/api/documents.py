from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database.db import get_db
from app.database.models import Document, Chunk
from app.services.chunking_service import chunk_text
from app.services.embedding_service import get_embeddings

router = APIRouter()


class DocumentCreate(BaseModel):
    title: str
    content: str


class DocumentResponse(BaseModel):
    id: int
    title: str
    chunk_count: int


@router.post("", status_code=status.HTTP_201_CREATED, response_model=DocumentResponse)
async def create_document(payload: DocumentCreate, db: Session = Depends(get_db)):
    db_document = Document(title=payload.title, content=payload.content)
    db.add(db_document)
    db.flush()
    chunked_payload = chunk_text(payload.content)
    vectors = await get_embeddings(chunked_payload)
    chunks_to_insert = [
        Chunk(content=c_content, document_id=db_document.id, embedding=vector)
        for c_content, vector in zip(chunked_payload, vectors)
    ]
    db.add_all(chunks_to_insert)
    db.commit()
    return {
        "id": db_document.id,
        "title": db_document.title,
        "chunk_count": len(chunked_payload)
    }
