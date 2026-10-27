"""Убрать users.unit — поле дублировало суффикс @vuz

План 038. Колонка `unit` («college»/«vuz») задумывалась как признак
подразделения, но подразделение уже закодировано в имени группы
суффиксом `@vuz`. Поле рассинхронизировалось: `/group` менял группу,
но не трогал `unit`, и на проде был человек с `group='АП-25оз@vuz'`
и `unit='college'`.

Хуже: у преподавателей группы нет вовсе, и `unit` у всех трёх
оставался «college» — поэтому преподаватель вуза видел колледжную
сетку звонков, 5 пар вместо 8. Теперь подразделение определяется по
парам через `CollegeLessonRepo.is_vuz_teacher`.

Единственное чтение поля (`cb_bell`) переписано; три записи удалены
вместе с `set_unit`.

Revision ID: 0010_drop_unit
Revises: 0009_time_note
Create Date: 2026-10-27
"""
from alembic import op
import sqlalchemy as sa

revision = "0010_drop_unit"
down_revision = "0009_time_note"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if "unit" in _columns("users"):
        with op.batch_alter_table("users") as batch:
            batch.drop_column("unit")


def downgrade() -> None:
    if "unit" not in _columns("users"):
        with op.batch_alter_table("users") as batch:
            batch.add_column(sa.Column("unit", sa.String(16),
                                       nullable=False, server_default="college"))
