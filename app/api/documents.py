import logging
from typing import List

from fastapi import APIRouter, Depends, status, HTTPException, Response, BackgroundTasks
from fastapi import Query
from sqlalchemy.orm import Session

from app.database.db import get_db
from app.database.models import Document
from app.schemas import DocumentCreate, DocumentResponse, DocumentDetail
from app.services.document_service import (
    get_documents,
    get_document_by_id,
    delete_document,
    process_document_background,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=DocumentResponse)
async def create_document(
        payload: DocumentCreate,
        background_tasks: BackgroundTasks,
        db: Session = Depends(get_db)
):
    db_document = Document(
        title=payload.title,
        content=payload.content,
        status="processing"
    )
    db.add(db_document)
    db.commit()

    background_tasks.add_task(
        process_document_background,
        document_id=db_document.id,
        content=payload.content
    )

    return {
        "id": db_document.id,
        "title": db_document.title,
        "status": "processing",
        "chunk_count": 0
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
            "status": doc.status,
            "chunk_count": len(doc.chunks) if doc.chunks else 0
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
        "content": db_document.content,
        "status": db_document.status,
        "chunk_count": len(db_document.chunks) if db_document.chunks else 0
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
