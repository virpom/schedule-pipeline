"""Убрать users.bell_notify — мёртвая колонка, разошедшаяся с bell_mode

План 121. Колонка осталась с `0001_baseline`, где помечена как
устаревшая. Рабочая настройка — `bell_mode` (`off`/`start_end`/`full`),
код читает только её.

Данные разошлись. На проде:

    bell_notify=1, но bell_mode='off'   -> 2 чел (звонки НЕ приходят)
    bell_notify=0, но bell_mode!='off'  -> 10 чел (звонки приходят)

То есть по базе нельзя понять, какая настройка настоящая: восемь
человек выглядят подписанными, из них двое не получают звонки.

Ещё колонка мешает миграциям: `Base.metadata` про неё не знает,
поэтому `create_all` в тестах создаёт `users` без неё, а прод — с ней.
При `alembic revision --autogenerate` она попадёт в diff как «удалить»,
и кто-то может удалить её вслепую.

Revision ID: 0011_drop_bell_notify
Revises: 0010_drop_unit
Create Date: 2026-10-27
"""
from alembic import op
import sqlalchemy as sa

revision = "0011_drop_bell_notify"
down_revision = "0010_drop_unit"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if "bell_notify" in _columns("users"):
        with op.batch_alter_table("users") as batch:
            batch.drop_column("bell_notify")


def downgrade() -> None:
    if "bell_notify" not in _columns("users"):
        with op.batch_alter_table("users") as batch:
            batch.add_column(sa.Column("bell_notify", sa.Integer(),
                                       server_default=sa.text("0")))
