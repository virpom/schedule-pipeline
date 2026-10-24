"""vuz: подразделение пользователя, справочник групп вуза, звонки, ширина предмета

Фундамент под расписание вуза. Само расписание появится позже — здесь
только то, без чего его нельзя положить в базу.

* ``users.unit`` — «колледж» или «вуз». Существующие пользователи
  становятся колледжем через server_default, переписывать ничего не нужно.
* ``vuz_group`` — справочник: группа → факультет, курс, форма обучения.
  Нужен, потому что по имени группы (``ЭК-26-1``) факультет не определить.
* Звонки вуза: 8 пар вместо 5, отдельная ``course_group='VUZ'``.
* ``subject`` → 256: в файлах вуза 168 ячеек длиннее 128 символов.

Revision ID: 0004_vuz
Revises: 0003_changed
Create Date: 2026-10-24
"""
import datetime

from alembic import op
import sqlalchemy as sa

revision = "0004_vuz"
down_revision = "0003_changed"
branch_labels = None
depends_on = None

# Сетка вуза: восемь пар. Взята из файлов `1-ochnoe.xls`.
# Пара хранится двумя академическими часами, как в bell_schedule.
VUZ_BELLS = [
    (1, "08:40", "09:25", "09:35", "10:10"),
    (2, "10:20", "11:05", "11:15", "11:50"),
    (3, "12:10", "12:55", "13:05", "13:40"),
    (4, "13:50", "14:35", "14:45", "15:20"),
    (5, "15:30", "16:15", "16:25", "17:00"),
    (6, "17:10", "17:55", "18:05", "18:40"),
    (7, "18:50", "19:35", "19:45", "20:20"),
    (8, "20:30", "21:15", "21:25", "22:00"),
]


def _t(value: str) -> datetime.time:
    return datetime.time.fromisoformat(value)


def upgrade() -> None:
    # 1. Подразделение пользователя. default 'college' — все существующие
    #    становятся студентами/преподавателями колледжа автоматически.
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("unit", sa.String(16), server_default="college",
                                   nullable=False))

    # 2. Справочник групп вуза: без него выбор группы по факультетам
    #    невозможен — факультет берётся из листа файла, не из имени группы.
    op.create_table(
        "vuz_group",
        sa.Column("name", sa.String(32), primary_key=True),
        sa.Column("faculty", sa.String(16), nullable=False),
        sa.Column("course", sa.Integer(), nullable=False),
        sa.Column("form", sa.String(16), nullable=False),
    )
    op.create_index("ix_vuz_group_faculty", "vuz_group", ["faculty"])

    # 3. Звонки вуза. Дублируем по day_type: format_day ищет по
    #    (day_type, course_group, para), а понедельник — отдельный тип.
    bells = sa.table(
        "bell_schedule",
        sa.column("day_type", sa.String),
        sa.column("course_group", sa.String),
        sa.column("para", sa.Integer),
        sa.column("start", sa.Time),
        sa.column("h1_end", sa.Time),
        sa.column("h2_start", sa.Time),
        sa.column("end", sa.Time),
    )
    op.bulk_insert(bells, [
        {
            "day_type": day_type,
            "course_group": "VUZ",
            "para": para,
            "start": _t(start),
            "h1_end": _t(h1_end),
            "h2_start": _t(h2_start),
            "end": _t(end),
        }
        for day_type in ("MONDAY", "OTHER")
        for para, start, h1_end, h2_start, end in VUZ_BELLS
    ])

    # 4. Ширина предмета. В файлах вуза есть ячейки до 462 символов.
    for table in ("base_lesson", "college_lesson", "substitution"):
        with op.batch_alter_table(table) as batch:
            batch.alter_column("subject", type_=sa.String(256), existing_nullable=False)

    # 5. Якорь учебной недели вуза: 31.08.2026 = неделя 1.
    #    Сверено на 38 датированных ячейках файла (35 совпадений).
    op.execute(
        "INSERT OR IGNORE INTO setting (key, value) "
        "VALUES ('vuz_week_anchor', '2026-08-31')"
    )


def downgrade() -> None:
    op.execute("DELETE FROM setting WHERE key = 'vuz_week_anchor'")
    for table in ("base_lesson", "college_lesson", "substitution"):
        with op.batch_alter_table(table) as batch:
            batch.alter_column("subject", type_=sa.String(128), existing_nullable=False)
    op.execute("DELETE FROM bell_schedule WHERE course_group = 'VUZ'")
    op.drop_index("ix_vuz_group_faculty", table_name="vuz_group")
    op.drop_table("vuz_group")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("unit")
