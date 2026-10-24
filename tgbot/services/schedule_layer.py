"""Сборка расписания из слоёв: базовое (по чётности) + замены.

Отдельный сервис, чтобы логику не дублировать между хендлерами
студента, старосты и поллером.
"""
import datetime

from common.schedule import SUB_CANCEL, is_vuz, week_parity
from infrastructure.database.repo.requests import RequestsRepo

# Колледж считает чётность на 1 иначе, чем ISO (26.10.2026 — ISO чётная,
# у колледжа нечётная). Дефолт, чтобы вызовы без аргумента не врали.
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
    """Итоговое расписание группы на дату."""
    parity = week_parity(date, parity_offset)

    # У вуза пары задаются списками недель, а не чётностью. Номер недели
    # считается от якоря, который лежит в настройках.
    week = None
    if is_vuz(group):
        from tgbot.services import sync_vuz
        anchor = await sync_vuz.get_anchor(repo)
        week = sync_vuz.vuz_week(date, anchor)

    base = await repo.base_lessons.get_day(group, date.isoweekday(), parity,
                                           week=week)
    # Для вуза week всегда задан, поэтому в base остаются только пары,
    # идущие на этой неделе, — по одной на номер пары. Склейка ниже
    # нужна колледжу, где на слот бывает и ODD, и ANY.
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
