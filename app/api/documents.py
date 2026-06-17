from typing import List

from fastapi import APIRouter, Depends, status, HTTPException, Response
from fastapi import Query
from sqlalchemy.orm import Session

from app.database.db import get_db
from app.database.models import Document, Chunk
from app.schemas import DocumentCreate, DocumentResponse, DocumentDetail
from app.services.chunking_service import chunk_text
from app.services.document_service import get_documents, get_document_by_id, delete_document
from app.services.embedding_service import get_embeddings

router = APIRouter()


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


@router.get("", response_model=List[DocumentResponse])
async def read_documents(
        limit: int = Query(default=10, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
        db: Session = Depends(get_db)
):
    documents = get_documents(db=db, limit=limit, offset=offset)
    return [
        {
            "id": doc.id,
            "title": doc.title,
            "chunk_count": len(doc.chunks)
        }
        for doc in documents
    ]


@router.get("/{id}", response_model=DocumentDetail)
async def read_document(id: int, db: Session = Depends(get_db)):
    db_document = get_document_by_id(db=db, document_id=id)
    if db_document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found"
        )

    return {
        "id": db_document.id,
        "title": db_document.title,
        "chunk_count": len(db_document.chunks),
        "content": db_document.content
    }


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_document(id: int, db: Session = Depends(get_db)):
    success = delete_document(db=db, document_id=id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found"
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
