import hashlib
import logging
import time

from sqlalchemy.orm import Session

from app.core.redis import get_redis_client
from app.database.db import get_db_context
from app.database.models import Document, Chunk
from app.services.chunking_service import chunk_text
from app.services.embedding_service import get_embeddings

logger = logging.getLogger(__name__)


def get_documents(
        db: Session,
        limit: int = 10,
        offset: int = 0,
):
    return db.query(Document).offset(offset).limit(limit).all()


def get_document_by_id(db: Session, document_id: int):
    return db.query(Document).filter(Document.id == document_id).first()


def delete_document(db: Session, document_id: int) -> bool:
    db_document = db.query(Document).filter(Document.id == document_id).first()
    if not db_document:
        return False

    db.delete(db_document)
    db.commit()
    return True


def invalidate_search_cache():
    redis_client = get_redis_client()
    keys_to_delete = list(redis_client.scan_iter("search:query:*"))
    if keys_to_delete:
        redis_client.delete(*keys_to_delete)


async def process_document_background(document_id: int, request_id: str, content: str):
    start_total = time.perf_counter()

    logger.info(
        "document_processing_started",
        extra={
            "document_id": document_id,
            "request_id": request_id
        }
    )

    with get_db_context() as db:
        try:
            start_chunk = time.perf_counter()
            chunked_payload = chunk_text(content)
            chunking_time_ms = (time.perf_counter() - start_chunk) * 1000

            start_embed = time.perf_counter()
            vectors = await get_embeddings(chunked_payload)
            embedding_time_ms = (time.perf_counter() - start_embed) * 1000

            total_processing_time_ms = (time.perf_counter() - start_total) * 1000

            chunks_to_insert = [
                Chunk(content=c_content, document_id=document_id, embedding=vector)
                for c_content, vector in zip(chunked_payload, vectors)
            ]
            db.bulk_save_objects(chunks_to_insert)

            db.query(Document).filter(Document.id == document_id).update({
                "status": "completed",
                "chunking_time_ms": chunking_time_ms,
                "embedding_time_ms": embedding_time_ms,
                "total_processing_time_ms": total_processing_time_ms
            })

            invalidate_search_cache()

            logger.info(
                "document_processing_completed",
                extra={
                    "document_id": document_id,
                    "request_id": request_id,
                    "chunk_count": len(chunked_payload),
                    "total_processing_time_ms": total_processing_time_ms
                }
            )

        except Exception as e:
            logger.error(
                "document_processing_failed",
                extra={
                    "document_id": document_id,
                    "request_id": request_id,
                    "error": str(e)
                },
                exc_info=True
            )
            db.rollback()
            db.query(Document).filter(Document.id == document_id).update({"status": "failed"})


def hash_content(content: str) -> str:
    return hashlib.sha256(content.strip().encode()).hexdigest()


def get_document_by_hash(db: Session, content_hash: str):
    return db.query(Document).filter(Document.content_hash == content_hash).first()
