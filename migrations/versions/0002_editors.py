"""editors: базовое расписание, замены, права старост, журнал, архив

Revision ID: 0002_editors
Revises: 0001_baseline
Create Date: 2026-10-16
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_editors"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Базовое расписание (чётная/нечётная неделя)
    op.create_table(
        "base_lesson",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("group", sa.String(32), nullable=False),
        sa.Column("week_parity", sa.String(4), nullable=False),
        sa.Column("weekday", sa.Integer(), nullable=False),
        sa.Column("para", sa.Integer(), nullable=False),
        sa.Column("subject", sa.String(128), nullable=False),
        sa.Column("teacher", sa.String(128), server_default=""),
        sa.Column("room", sa.String(64), server_default=""),
        sa.Column("source", sa.String(8), server_default="manual"),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("group", "week_parity", "weekday", "para",
                            name="uc_base_lesson"),
    )
    op.create_index("ix_base_lesson_group", "base_lesson", ["group"])

    # 2. Замены на конкретную дату
    op.create_table(
        "substitution",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("group", sa.String(32), nullable=False),
        sa.Column("para", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(8), nullable=False),
        sa.Column("subject", sa.String(128), server_default=""),
        sa.Column("teacher", sa.String(128), server_default=""),
        sa.Column("room", sa.String(64), server_default=""),
        sa.Column("comment", sa.String(256), server_default=""),
        sa.Column("source", sa.String(8), server_default="manual"),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("date", "group", "para", name="uc_substitution"),
    )
    op.create_index("ix_substitution_date", "substitution", ["date"])
    op.create_index("ix_substitution_group", "substitution", ["group"])

    # 3. Права редакторов (старост)
    op.create_table(
        "schedule_editor",
        sa.Column("user_id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("group", sa.String(32), nullable=False),
        sa.Column("granted_by", sa.BigInteger(), nullable=True),
        sa.Column("granted_at", sa.DateTime(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("1")),
    )
    op.create_index("ix_schedule_editor_group", "schedule_editor", ["group"])

    # 4. Журнал правок
    op.create_table(
        "schedule_edit",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("group", sa.String(32), nullable=False),
        sa.Column("date", sa.Date(), nullable=True),
        sa.Column("para", sa.Integer(), nullable=True),
        sa.Column("layer", sa.String(8), server_default="base"),
        sa.Column("action", sa.String(8), server_default="edit"),
        sa.Column("old_value", sa.String(1024), server_default=""),
        sa.Column("new_value", sa.String(1024), server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_schedule_edit_user_id", "schedule_edit", ["user_id"])
    op.create_index("ix_schedule_edit_group", "schedule_edit", ["group"])

    # 5. Архив прошедших дней
    op.create_table(
        "day_snapshot",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("group", sa.String(32), nullable=False),
        sa.Column("payload", sa.String(4096), server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("date", "group", name="uc_day_snapshot"),
    )
    op.create_index("ix_day_snapshot_date", "day_snapshot", ["date"])
    op.create_index("ix_day_snapshot_group", "day_snapshot", ["group"])

    # 6. Технические поля существующих таблиц.
    #    batch_alter_table — потому что SQLite не умеет ALTER COLUMN.
    with op.batch_alter_table("college_lesson") as batch:
        batch.add_column(sa.Column("source", sa.String(8), server_default="site"))

    with op.batch_alter_table("college_lesson") as batch:
        batch.create_index("ix_college_lesson_teacher", ["teacher"])


def downgrade() -> None:
    with op.batch_alter_table("college_lesson") as batch:
        batch.drop_index("ix_college_lesson_teacher")
        batch.drop_column("source")
    op.drop_table("day_snapshot")
    op.drop_table("schedule_edit")
    op.drop_table("schedule_editor")
    op.drop_table("substitution")
    op.drop_table("base_lesson")
