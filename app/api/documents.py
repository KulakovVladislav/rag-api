import logging
from typing import List

from fastapi import APIRouter, Depends, status, HTTPException, Response, BackgroundTasks
from fastapi import Query
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.context import request_id_ctx
from app.database.db import get_db
from app.database.models import Document
from app.schemas import DocumentCreate, DocumentResponse, DocumentDetail
from app.services.document_service import (
    get_documents,
    get_document_by_id,
    delete_document,
    process_document_background,
    hash_content,
    get_document_by_hash
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=DocumentResponse)
async def create_document(
        payload: DocumentCreate,
        background_tasks: BackgroundTasks,
        db: Session = Depends(get_db)
):
    cleaned_content = payload.content.strip()
    file_hash = hash_content(cleaned_content)

    existing_doc = get_document_by_hash(db, file_hash)
    if existing_doc:
        return JSONResponse(
            status_code=409,
            content={
                "detail": "Document with identical content already exists",
                "existing_document_id": existing_doc.id
            }
        )

    db_document = Document(
        title=payload.title,
        content=cleaned_content,
        content_hash=file_hash,
        status="processing",
        doc_metadata=payload.doc_metadata
    )
    db.add(db_document)

    try:
        db.commit()
    except IntegrityError:

        db.rollback()
        existing_doc = get_document_by_hash(db, file_hash)
        return JSONResponse(
            status_code=409,
            content={
                "detail": "Document with identical content already exists",
                "existing_document_id": existing_doc.id if existing_doc else None
            }
        )

    db.refresh(db_document)

    try:
        current_request_id = request_id_ctx.get()
    except LookupError:
        current_request_id = ""

    background_tasks.add_task(
        process_document_background,
        document_id=db_document.id,
        request_id=current_request_id,
        content=cleaned_content
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
        "chunk_count": len(db_document.chunks) if db_document.chunks else 0,
        "chunking_time_ms": db_document.chunking_time_ms,
        "embedding_time_ms": db_document.embedding_time_ms,
        "total_processing_time_ms": db_document.total_processing_time_ms,
        "metadata": db_document.doc_metadata,
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
