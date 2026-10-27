"""time_note: время пары из ячейки доходит до студента

План 032. В файле колледжа время пары иногда стоит прямо в тексте
ячейки: «с 18.00 до 21.00 - Общая энергетика». Парсер это корректно
разбирал (`_strip_time_note`), складывал в `BaseLesson.time_note` — и
дальше некуда: колонки в БД не было, поле терялось.

Пять пар идут не по звонку. Худший случай — ТЭф-24 вторник: пара с
18:00, а бот показывал 16:20–17:55 по звонку пятой пары. Студент
приходил на два часа раньше или вообще не приходил вечером.

`time_note` бывает двух видов: настоящее время («с 18.00 до 21.00») и
подтверждение номера («5-я пара»). Второе дублирует звонок и только
зашумит вывод, поэтому показываем его лишь когда номер не совпадает.

Revision ID: 0009_time_note
Revises: 0008_room_len
Create Date: 2026-10-27
"""
from alembic import op
import sqlalchemy as sa

revision = "0009_time_note"
down_revision = "0008_room_len"
branch_labels = None
depends_on = None

TABLES = ("base_lesson", "college_lesson")


def _columns(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    for table in TABLES:
        if "time_note" not in _columns(table):
            with op.batch_alter_table(table) as batch:
                batch.add_column(sa.Column("time_note", sa.String(64),
                                           nullable=False, server_default=""))


def downgrade() -> None:
    for table in TABLES:
        if "time_note" in _columns(table):
            with op.batch_alter_table(table) as batch:
                batch.drop_column("time_note")
