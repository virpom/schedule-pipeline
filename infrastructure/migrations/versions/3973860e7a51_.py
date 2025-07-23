"""empty message

Revision ID: 3973860e7a51
Revises: 4937487fcf2e
Create Date: 2024-12-17 17:24:34.975681

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3973860e7a51'
down_revision: Union[str, None] = '4937487fcf2e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
