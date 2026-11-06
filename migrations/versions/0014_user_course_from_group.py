"""users.course: пересчитать из номера группы

Курс колледжа раньше спрашивали у человека кнопками «1 курс … 4 курс»
и хранили в users.course. Люди отвечали наугад: на проде 9 записей из
297 разошлись с тем, что следует из имени группы. Самое заметное —
ДП-26 стоял как 3 курс (верно 1), из-за чего человек получал звонки
чужого потока: у колледжа 1 и 4 курс — один поток, 2 и 3 — другой.

Курс однозначно выводится из номера набора: ДП-26 → 1, ЭК-23 → 4.
Теперь его считает code (course_from_group), а миграция приводит к
тому же виду уже записанные строки.

Трогаем только тех, у кого группа есть и кто не преподаватель:
у преподавателя курс не имеет смысла, а без группы его не из чего
вычислить.

Revision ID: 0014_user_course_from_group
Revises: 0013_chat_status
Create Date: 2026-11-06
"""
import datetime
import re

from alembic import op
import sqlalchemy as sa

revision = "0014_user_course_from_group"
down_revision = "0013_chat_status"
branch_labels = None
depends_on = None


def _course(group: str, now: datetime.datetime | None = None) -> int:
    """Копия common.schedule.course_from_group.

    Копия, а не импорт: миграция должна остаться рабочей, даже если
    функцию потом перепишут или удалят.
    """
    m = re.search(r"(\d{2})", group)
    if not m:
        return 1
    admission = 2000 + int(m.group(1))
    # Локальное время, не UTC: учебный год начинается 1 сентября по
    # местному, а в UTC это 31 августа 17:00. Миграция одноразовая и
    # пишет в базу навсегда — ошибка тут не исправляется сама.
    now = now or datetime.datetime.now()
    acad_start = now.year if now.month >= 9 else now.year - 1
    return max(1, acad_start - admission + 1)


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(sa.text(
        'select id, "group", course from users '
        'where "group" is not null and "group" <> \'\' '
        "and (role is null or role <> 'teacher')"
    )).fetchall()
    fixed = 0
    for uid, group, course in rows:
        want = _course(group)
        if course != want:
            conn.execute(
                sa.text("update users set course = :c where id = :i"),
                {"c": want, "i": uid},
            )
            fixed += 1
    if fixed:
        print(f"users.course: пересчитано {fixed} записей из {len(rows)}")


def downgrade() -> None:
    """Откат не восстанавливает прежние (ошибочные) значения.

    Вернуть 3 курс для ДП-26 значило бы вернуть дефект: пары и звонки
    снова поехали бы. Возвращаем таблицу к виду «курс неизвестен», от
    которого код не зависит — он считает курс из группы.
    """
    op.get_bind().execute(sa.text("update users set course = null"))
