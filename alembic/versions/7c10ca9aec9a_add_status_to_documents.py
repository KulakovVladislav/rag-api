"""add_status_to_documents

Revision ID: 7c10ca9aec9a
Revises: ab8ab01e1746
Create Date: 2026-06-19 12:39:14.511676

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '7c10ca9aec9a'
down_revision: Union[str, Sequence[str], None] = 'ab8ab01e1746'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'documents',
        sa.Column('status', sa.String(length=20), server_default='completed', nullable=False)
    )


def downgrade() -> None:
    op.drop_column('documents', 'status')
