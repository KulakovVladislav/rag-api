"""add_metadata_to_documents

Revision ID: 1b2935db608f
Revises: 729150e3abb0
Create Date: 2026-07-14 16:36:58.760246

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '1b2935db608f'
down_revision: Union[str, Sequence[str], None] = '729150e3abb0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'documents',
        sa.Column("metadata", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column('documents', 'metadata')
