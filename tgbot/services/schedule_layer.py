"""Сборка расписания из слоёв: базовое (по чётности) + замены.

Отдельный сервис, чтобы логику не дублировать между хендлерами
студента, старосты и поллером.
"""
import datetime

from common.schedule import PARITY_ANY, SUB_CANCEL, week_parity
from infrastructure.database.repo.requests import RequestsRepo

# Колледж считает чётность иначе, чем ISO: 26.10.2026 — это ISO-неделя 44
# (чётная), а у колледжа она нечётная. Сдвиг вынесен сюда как значение по
# умолчанию, чтобы его не забыли передать: раньше хендлеры старосты вызывали
# get_day_slots() без аргумента и показывали не ту неделю.
PARITY_OFFSET = 1


class Slot:
    """Итоговая пара дня — то, что видит студент."""

    __slots__ = ("para", "subject", "teacher", "room", "changed", "action", "comment")

    def __init__(self, para: int, subject: str, teacher: str = "", room: str = "",
                 changed: bool = False, action: str = "", comment: str = ""):
        self.para = para
        self.subject = subject
        self.teacher = teacher
        self.room = room
        self.changed = changed      # пришло из замены
        self.action = action        # replace | add | ""
        self.comment = comment

    def __repr__(self):
        return f"<Slot {self.para} {self.subject}{' (замена)' if self.changed else ''}>"


async def get_day_slots(repo: RequestsRepo, group: str, date: datetime.date,
                        parity_offset: int = PARITY_OFFSET) -> list[Slot]:
    """Итоговое расписание группы на дату.

    parity_offset по умолчанию — сдвиг колледжа, а не ISO.
    """
    parity = week_parity(date, parity_offset)
    base = await repo.base_lessons.get_day(group, date.isoweekday(), parity)
    subs = await repo.substitutions.get_for_date(group, date)

    sub_by_para = {s.para: s for s in subs}
    slots: list[Slot] = []
    used: set[int] = set()

    for lesson in base:
        sub = sub_by_para.get(lesson.para)
        used.add(lesson.para)
        if sub and sub.action == SUB_CANCEL:
            continue
        if sub and sub.action in ("replace", "add"):
            slots.append(Slot(lesson.para, sub.subject, sub.teacher, sub.room,
                              changed=True, action=sub.action, comment=sub.comment))
        else:
            slots.append(Slot(lesson.para, lesson.subject, lesson.teacher, lesson.room))

    # «Добавить» на пару, которая уже есть в базе, — это фактически замена:
    # второй слот на тот же номер пары создавать нельзя.
    for para, sub in sorted(sub_by_para.items()):
        if sub.action == "add" and para not in used:
            slots.append(Slot(para, sub.subject, sub.teacher, sub.room,
                              changed=True, action=sub.action, comment=sub.comment))

    slots.sort(key=lambda s: s.para)
    return slots


async def get_week_slots(repo: RequestsRepo, group: str,
                         start: datetime.date | None = None,
                         parity_offset: int = 0) -> list[tuple[datetime.date, list[Slot]]]:
    """Расписание группы на 7 дней начиная с понедельника."""
    if start is None:
        today = datetime.date.today()
        start = today - datetime.timedelta(days=today.weekday())
    result = []
    for i in range(7):
        d = start + datetime.timedelta(days=i)
        slots = await get_day_slots(repo, group, d, parity_offset)
        result.append((d, slots))
    return result


async def has_base(repo: RequestsRepo, group: str) -> bool:
    """Есть ли у группы вообще базовое расписание."""
    for parity in ("ODD", "EVEN", PARITY_ANY):
        if await repo.base_lessons.get_week(group, parity):
            return True
    return False
