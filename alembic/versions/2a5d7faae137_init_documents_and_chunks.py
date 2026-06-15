import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision = '2a5d7faae137'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        'documents',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_documents_id'), 'documents', ['id'], unique=False)

    op.create_table(
        'chunks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('document_id', sa.Integer(), nullable=False),
        sa.Column('embedding', Vector(384), nullable=False),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_chunks_id'), 'chunks', ['id'], unique=False)
    op.execute("""
               CREATE INDEX chunks_embedding_hnsw_idx
                   ON chunks USING hnsw (embedding vector_cosine_ops)
                   WITH (m = 16, ef_construction = 64)
               """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS chunks_embedding_hnsw_idx")
    op.drop_index(op.f('ix_chunks_id'), table_name='chunks')
    op.drop_table('chunks')
    op.drop_index(op.f('ix_documents_id'), table_name='documents')
    op.drop_table('documents')
