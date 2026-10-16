"""baseline: схема до внедрения alembic (как в боевой БД)

Revision ID: 0001_baseline
Revises:
Create Date: 2026-10-16

Отражает реальную схему продовой SQLite: college_lesson БЕЗ id,
users с bell_notify (устаревшее) и т.д.
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("username", sa.String(128), nullable=True),
        sa.Column("full_name", sa.String(128), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("1")),
        sa.Column("language", sa.String(10), server_default=sa.text("'ru'")),
        sa.Column("group", sa.String(32), nullable=True),
        sa.Column("subscribed", sa.Boolean(), server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("bell_detail", sa.String(16), server_default=sa.text("'brief'")),
        sa.Column("last_seen", sa.DateTime(), nullable=True),
        sa.Column("send_image", sa.Integer(), server_default=sa.text("1")),
        sa.Column("bell_notify", sa.Integer(), server_default=sa.text("0")),
        sa.Column("role", sa.String(16), server_default=sa.text("'student'")),
        sa.Column("teacher_name", sa.String(128), nullable=True),
        sa.Column("bell_mode", sa.String(16), server_default=sa.text("'off'")),
        sa.Column("course", sa.Integer(), nullable=True),
    )

    op.create_table(
        "college_lesson",
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("group", sa.String(32), nullable=False),
        sa.Column("para", sa.Integer(), nullable=False),
        sa.Column("para_end", sa.Integer(), nullable=False),
        sa.Column("subject", sa.String(128), nullable=False),
        sa.Column("teacher", sa.String(128), nullable=False),
        sa.Column("room", sa.String(64), nullable=False),
        sa.Column("source_url", sa.String(512), nullable=False),
    )
    op.create_index("ix_college_lesson_date", "college_lesson", ["date"])
    op.create_index("ix_college_lesson_group", "college_lesson", ["group"])

    op.create_table(
        "no_lessons",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("group", sa.String(32), nullable=False),
        sa.Column("note", sa.String(256)),
        sa.UniqueConstraint("date", "group", name="uc_no_lessons"),
    )
    op.create_index("ix_no_lessons_date", "no_lessons", ["date"])
    op.create_index("ix_no_lessons_group", "no_lessons", ["group"])

    op.create_table(
        "schedule_file",
        sa.Column("date", sa.Date(), primary_key=True),
        sa.Column("content_hash", sa.String(64), nullable=False),
    )

    op.create_table(
        "setting",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("value", sa.String(128), nullable=False),
    )

    op.create_table(
        "bell_schedule",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("day_type", sa.String(16), nullable=False),
        sa.Column("course_group", sa.String(16), nullable=False),
        sa.Column("para", sa.Integer(), nullable=False),
        sa.Column("start", sa.Time(), nullable=False),
        sa.Column("h1_end", sa.Time(), nullable=False),
        sa.Column("h2_start", sa.Time(), nullable=False),
        sa.Column("end", sa.Time(), nullable=False),
        sa.UniqueConstraint("day_type", "course_group", "para", name="uc_bell_schedule"),
    )

    op.create_table(
        "bell_lunch",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("day_type", sa.String(16), nullable=False),
        sa.Column("course_group", sa.String(16), nullable=False),
        sa.Column("para", sa.Integer(), nullable=False),
        sa.Column("position", sa.String(8), nullable=False),
        sa.Column("lunch_start", sa.Time(), nullable=False),
        sa.Column("lunch_end", sa.Time(), nullable=False),
        sa.UniqueConstraint("day_type", "course_group", name="uc_bell_lunch"),
    )

    op.create_table(
        "bell_reminder",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("key", sa.String(32), nullable=False),
        sa.UniqueConstraint("user_id", "date", "key", name="uc_bell_reminder"),
    )

    op.create_table(
        "chats",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("title", sa.String(128)),
        sa.Column("group", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )


def downgrade() -> None:
    for t in ("chats", "bell_reminder", "bell_lunch", "bell_schedule",
              "setting", "schedule_file", "no_lessons", "college_lesson", "users"):
        op.drop_table(t)
