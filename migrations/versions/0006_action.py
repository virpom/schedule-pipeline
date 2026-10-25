"""college_lesson: колонка action — чтобы отмена не выглядела заменой

Отменённая пара остаётся в материализованной таблице (иначе студент
видит пустое место и не знает об отмене), но признак «это отмена»
хранить было негде: было только ``changed``, а оно означает «пришло
из листка замен». Отмена рисовалась значком замены.

Revision ID: 0006_action
Revises: 0005_weeks
Create Date: 2026-10-25
"""
from alembic import op
import sqlalchemy as sa

revision = "0006_action"
down_revision = "0005_weeks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("college_lesson") as batch:
        batch.add_column(sa.Column("action", sa.String(8), nullable=False,
                                   server_default=""))


def downgrade() -> None:
    with op.batch_alter_table("college_lesson") as batch:
        batch.drop_column("action")
