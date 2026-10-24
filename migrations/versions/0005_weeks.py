"""vuz: недели пары отдельной колонкой

В вузе в один слот (группа, день, пара) бывает 2–4 разных предмета на
разных неделях. Пример, ``ЭК-26-2`` понедельник 7-я пара:

    недели 6,8,10,12,14,16   Экономическая теория
    недели 5,7,9,11,13       Навыки презентаций
    недели 15,17             Аналитическая геометрия

Существующий уникальный ключ ``(group, week_parity, weekday, para)``
такое не вмещает: все три пары получили бы ``week_parity='ANY'`` и
один ключ. Поэтому недели выносим в колонку ``weeks`` — строку вида
``"6,8,10,12,14,16"`` — и включаем её в уникальный ключ.

У колледжа ``weeks`` пустая, поведение не меняется.

Revision ID: 0005_weeks
Revises: 0004_vuz
Create Date: 2026-10-24
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_weeks"
down_revision = "0004_vuz"
branch_labels = None
depends_on = None

def upgrade() -> None:
    # college_lesson не трогаем: там пары уже разложены по датам, недель нет.
    with op.batch_alter_table("base_lesson") as batch:
        batch.add_column(sa.Column("weeks", sa.String(128), nullable=False,
                                   server_default=""))
    with op.batch_alter_table("base_lesson") as batch:
        batch.drop_constraint("uc_base_lesson", type_="unique")
        batch.create_unique_constraint(
            "uc_base_lesson",
            ["group", "week_parity", "weekday", "para", "weeks"])


def downgrade() -> None:
    with op.batch_alter_table("base_lesson") as batch:
        batch.drop_constraint("uc_base_lesson", type_="unique")
        batch.create_unique_constraint(
            "uc_base_lesson", ["group", "week_parity", "weekday", "para"])
    with op.batch_alter_table("base_lesson") as batch:
        batch.drop_column("weeks")
