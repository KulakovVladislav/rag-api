import logging
from contextlib import closing

from sqlalchemy.orm import Session

from app.core.redis import get_redis_client
from app.database.db import get_db
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


async def process_document_background(document_id: int, content: str):
    with closing(next(get_db())) as db:
        try:
            chunked_payload = chunk_text(content)
            vectors = await get_embeddings(chunked_payload)

            chunks_to_insert = [
                Chunk(content=c_content, document_id=document_id, embedding=vector)
                for c_content, vector in zip(chunked_payload, vectors)
            ]
            db.add_all(chunks_to_insert)

            db.query(Document).filter(Document.id == document_id).update({"status": "completed"})
            db.commit()

            invalidate_search_cache()

        except Exception as e:
            logger.error(f"Error processing document {document_id}: {e}", exc_info=True)
            db.rollback()
            db.query(Document).filter(Document.id == document_id).update({"status": "failed"})
            db.commit()
