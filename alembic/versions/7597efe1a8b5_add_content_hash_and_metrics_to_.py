"""add_content_hash_and_metrics_to_documents

Revision ID: 7597efe1a8b5
Revises: ce5bffa2623f
Create Date: 2026-07-06 11:29:28.378590

"""
import hashlib
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '7597efe1a8b5'
down_revision: Union[str, Sequence[str], None] = 'ce5bffa2623f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'documents',
        sa.Column('content_hash', sa.String(64), nullable=True)
    )
    op.add_column(
        'documents',
        sa.Column('chunking_time_ms', sa.Float, nullable=True)
    )
    op.add_column(
        'documents',
        sa.Column('embedding_time_ms', sa.Float, nullable=True)
    )
    op.add_column(
        'documents',
        sa.Column('total_processing_time_ms', sa.Float, nullable=True)
    )

    connection = op.get_bind()
    documents = connection.execute(sa.text("SELECT id, content FROM documents"))
    for doc in documents:
        hash_value = hashlib.sha256(doc.content.encode()).hexdigest()
        connection.execute(
            sa.text("UPDATE documents SET content_hash = :h WHERE id = :id"),
            {"h": hash_value, "id": doc.id}
        )

    op.alter_column('documents', 'content_hash', nullable=False)
    op.create_index('idx_documents_content_hash', 'documents', ['content_hash'])


def downgrade() -> None:
    op.drop_index('idx_documents_content_hash', 'documents')
    op.drop_column('documents', 'content_hash')
    op.drop_column('documents', 'chunking_time_ms')
    op.drop_column('documents', 'embedding_time_ms')
    op.drop_column('documents', 'total_processing_time_ms')
