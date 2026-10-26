"""bell_reminder.event_key и уникальный ключ college_lesson

План 048. Модель ``BellReminder`` и боевая база называют колонку
``event_key`` (VARCHAR(64)), а baseline создаёт ``key`` (VARCHAR(32)).
На базе, поднятой миграциями, каждый запрос репозитория падал с
``no such column: bell_reminder.event_key`` — звонки не приходили
никогда.

План 047. Baseline создаёт ``college_lesson`` без ``id`` и без
``UNIQUE (date, group, para)``, хотя модель требует и то и другое.
На такой базе дубликат пары вставляется молча, и материализация
плодит строки вместо перезаписи.

Обе правки идемпотентны: на проде колонка уже называется правильно, а
уникальный ключ уже есть — там шаг просто ничего не делает.

Revision ID: 0007_bell_reminder
Revises: 0006_action
Create Date: 2026-10-27
"""
from alembic import op
import sqlalchemy as sa

revision = "0007_bell_reminder"
down_revision = "0006_action"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def _unique_names(table: str) -> set[str]:
    return {c["name"] for c in
            sa.inspect(op.get_bind()).get_unique_constraints(table)}


def upgrade() -> None:
    cols = _columns("bell_reminder")
    if "key" in cols and "event_key" not in cols:
        with op.batch_alter_table("bell_reminder") as batch:
            batch.alter_column("key", new_column_name="event_key",
                               type_=sa.String(64))

    # SQLite не умеет ADD CONSTRAINT, а batch_alter_table пересоздаёт
    # таблицу — это и нужно: id и уникальный ключ появляются сразу.
    #
    # create_primary_key обязателен: add_column с primary_key=True
    # создаёт обычную NOT NULL колонку без PRIMARY KEY, и тогда каждая
    # вставка падает с «NOT NULL constraint failed: college_lesson.id» —
    # SQLite автозаполняет только настоящий INTEGER PRIMARY KEY.
    if "id" not in _columns("college_lesson"):
        with op.batch_alter_table("college_lesson") as batch:
            batch.add_column(sa.Column("id", sa.Integer(), nullable=False))
            batch.create_primary_key("pk_college_lesson", ["id"])
    if "uc_college_lesson" not in _unique_names("college_lesson"):
        with op.batch_alter_table("college_lesson") as batch:
            batch.create_unique_constraint(
                "uc_college_lesson", ["date", "group", "para"])


def downgrade() -> None:
    cols = _columns("bell_reminder")
    if "event_key" in cols and "key" not in cols:
        with op.batch_alter_table("bell_reminder") as batch:
            batch.alter_column("event_key", new_column_name="key",
                               type_=sa.String(32))

    if "uc_college_lesson" in _unique_names("college_lesson"):
        with op.batch_alter_table("college_lesson") as batch:
            batch.drop_constraint("uc_college_lesson", type_="unique")
    if "id" in _columns("college_lesson"):
        with op.batch_alter_table("college_lesson") as batch:
            batch.drop_column("id")
