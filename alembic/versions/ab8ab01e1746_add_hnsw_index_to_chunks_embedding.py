"""add_hnsw_index_to_chunks_embedding

Revision ID: ab8ab01e1746
Revises: 2a5d7faae137
Create Date: 2026-06-17 10:51:15.654453

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'ab8ab01e1746'
down_revision: Union[str, Sequence[str], None] = '2a5d7faae137'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
               CREATE INDEX idx_chunks_embedding_hnsw
                   ON chunks
                   USING hnsw (embedding vector_cosine_ops);
               """)


def downgrade() -> None:
    op.execute("""
               DROP INDEX IF EXISTS idx_chunks_embedding_hnsw;
               """)
