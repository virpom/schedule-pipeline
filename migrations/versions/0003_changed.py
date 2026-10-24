"""college_lesson.changed: признак «эта пара пришла из замены»

Нужно, чтобы пометить замену значком в расписании. Раньше признак жил
только в ``Slot.changed`` внутри ``get_day_slots()`` и терялся при
материализации — до экрана студента не доходил.

Отдельная колонка, а не ``source='substitution'``: ``materialize()``
считает ``source != 'site'`` ручной правкой старосты и переносит такие
строки как есть. Замена, записанная в ``source``, застряла бы навсегда.

Revision ID: 0003_changed
Revises: 0002_editors
Create Date: 2026-10-24
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_changed"
down_revision = "0002_editors"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "college_lesson",
        sa.Column("changed", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    with op.batch_alter_table("college_lesson") as batch:
        batch.drop_column("changed")
