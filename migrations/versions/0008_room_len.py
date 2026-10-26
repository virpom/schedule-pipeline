"""room расширен до 512 — в нём лежат ссылки на онлайн-пары

План 021. Вуз публикует кабинет и ссылку на дистанционную пару в одной
колонке «ауд». Ссылки — `https://teams.microsoft.com/meet/…` и
`https://telemost.yandex.ru/j/…`, до 70 символов.

Колонка была `VARCHAR(64)`, и `sync_vuz` честно резал значение по 64:
ссылка сохранялась огрызком и не открывалась. То есть даже после
починки парсера студент не смог бы подключиться к паре.

64 -> 512 с запасом: у других провайдеров ссылки длиннее, а лишние
448 байт на строку при 2600 строках — 1 МБ, не проблема.

Идемпотентно: если колонка уже шире, шаг ничего не делает.

Revision ID: 0008_room_len
Revises: 0007_bell_reminder
Create Date: 2026-10-27
"""
from alembic import op
import sqlalchemy as sa

revision = "0008_room_len"
down_revision = "0007_bell_reminder"
branch_labels = None
depends_on = None

WANT = 512
TABLES = ("base_lesson", "college_lesson")


def _room_length(table: str) -> int | None:
    for col in sa.inspect(op.get_bind()).get_columns(table):
        if col["name"] == "room":
            return getattr(col["type"], "length", None)
    return None


def upgrade() -> None:
    for table in TABLES:
        length = _room_length(table)
        if length is not None and length < WANT:
            with op.batch_alter_table(table) as batch:
                batch.alter_column("room", type_=sa.String(WANT),
                                   existing_nullable=False,
                                   existing_server_default="")


def downgrade() -> None:
    for table in TABLES:
        length = _room_length(table)
        if length is not None and length > 64:
            # Обрезаем до 64 перед сужением, иначе SQLite оставит
            # значения длиннее объявленной длины.
            op.execute(
                f"UPDATE {table} SET room = substr(room, 1, 64) "
                f"WHERE length(room) > 64"
            )
            with op.batch_alter_table(table) as batch:
                batch.alter_column("room", type_=sa.String(64),
                                   existing_nullable=False,
                                   existing_server_default="")
