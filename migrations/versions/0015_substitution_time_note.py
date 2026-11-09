"""substitution: время вместо номера пары (вечерние занятия)

Колледж пишет вечернюю пару как «с 18.00 до 21.00» в графе номера.
Раньше из этой строки выдёргивались цифры 18 и 21, и в базе появлялись
пары 0, 8 и 2 — а студент видел «7) пара 7 ❌ отменено»: строку без
времени и без смысла.

Номер пары у вечерней всегда 1 (она первая по счёту), а время едет в
отдельную колонку и подставляется вместо звонков.

Пустое значение — обычная пара по звонкам, поведение не меняется.
"""
from alembic import op
import sqlalchemy as sa

revision = "0015_substitution_time_note"
down_revision = "0014_user_course_from_group"
branch_labels = None
depends_on = None


def _cols() -> set[str]:
    insp = sa.inspect(op.get_bind())
    return {c["name"] for c in insp.get_columns("substitution")}


def upgrade() -> None:
    if "time_note" not in _cols():
        # String(64) — как у одноимённой колонки в college_lesson:
        # «с 18.00 до 21.00» занимает 17 символов, запас большой.
        op.add_column(
            "substitution",
            sa.Column("time_note", sa.String(64), nullable=False,
                      server_default=""),
        )


def downgrade() -> None:
    if "time_note" in _cols():
        op.drop_column("substitution", "time_note")
