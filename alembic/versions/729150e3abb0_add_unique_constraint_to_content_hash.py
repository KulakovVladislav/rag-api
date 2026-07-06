"""add_unique_constraint_to_content_hash

Revision ID: 729150e3abb0
Revises: 7597efe1a8b5
Create Date: 2026-07-06 17:48:52.143764

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '729150e3abb0'
down_revision: Union[str, Sequence[str], None] = '7597efe1a8b5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index('idx_documents_content_hash', table_name='documents')
    op.create_unique_constraint(
        'uq_documents_content_hash',
        'documents',
        ['content_hash']
    )


def downgrade() -> None:
    op.drop_constraint('uq_documents_content_hash', 'documents', type_='unique')
    op.create_index('idx_documents_content_hash', 'documents', ['content_hash'])
