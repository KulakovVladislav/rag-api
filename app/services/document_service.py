from sqlalchemy.orm import Session


def get_documents(
        db: Session,
        limit: int = 10,
        offset: int = 0,
):
    return db.query(Document).offset(offset).limit(limit).all()


def get_document_by_id(db: Session, document_id: int):
    return db.query(Document).filter(Document.id == document_id).first()


from sqlalchemy.orm import Session
from app.database.models import Document


def delete_document(db: Session, document_id: int) -> bool:
    db_document = db.query(Document).filter(Document.id == document_id).first()
    if not db_document:
        return False

    db.delete(db_document)
    db.commit()
    return True
