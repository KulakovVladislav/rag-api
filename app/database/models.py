from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, Integer, String, Text, ForeignKey, Float
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.database.base import Base


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    # server_default='completed' applies only during raw SQL INSERT without explicit column specification
    # (for example, during a backfill in an Alembic migration). SQLAlchemy ORM always passes default='processing'
    # explicitly in the INSERT when creating a new Document via the ORM — therefore, server_default
    # during normal usage is unreachable, it only acts as a fallback for direct SQL inserts that bypass the ORM.
    status = Column(String(20), server_default='completed', default='processing')

    content_hash = Column(String(64), nullable=False)
    chunking_time_ms = Column(Float, nullable=True)
    embedding_time_ms = Column(Float, nullable=True)
    total_processing_time_ms = Column(Float, nullable=True)
    doc_metadata = Column("metadata", JSONB, nullable=True)

    chunks = relationship(
        "Chunk",
        back_populates="document",
        cascade="all, delete-orphan"
    )


class Chunk(Base):
    __tablename__ = "chunks"

    id = Column(Integer, primary_key=True, index=True)
    content = Column(Text, nullable=False)
    document_id = Column(Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)

    embedding = Column(Vector(384), nullable=False)

    document = relationship("Document", back_populates="chunks")
