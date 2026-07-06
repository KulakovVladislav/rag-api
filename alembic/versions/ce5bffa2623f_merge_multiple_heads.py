"""merge multiple heads

Revision ID: ce5bffa2623f
Revises: 7c10ca9aec9a, c1698571fb87
Create Date: 2026-06-22 10:34:38.202633

"""
from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = 'ce5bffa2623f'
down_revision: Union[str, Sequence[str], None] = ('7c10ca9aec9a', 'c1698571fb87')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
