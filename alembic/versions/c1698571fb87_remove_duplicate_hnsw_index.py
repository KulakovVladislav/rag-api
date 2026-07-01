"""remove_duplicate_hnsw_index

Revision ID: c1698571fb87
Revises: 7c10ca9aec9a
Create Date: 2026-06-22 10:05:31.312548

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c1698571fb87'
down_revision: Union[str, Sequence[str], None] = 'ab8ab01e1746'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_index('idx_chunks_embedding_hnsw', table_name='chunks')


def downgrade() -> None:
    """Downgrade schema."""
    op.create_index(
        'idx_chunks_embedding_hnsw',
        'chunks',
        ['embedding'],
        postgresql_using='hnsw',
        postgresql_ops={'embedding': 'vector_cosine_ops'}
    )
