"""Сборка расписания из слоёв: базовое (по чётности) + замены.

Отдельный сервис, чтобы логику не дублировать между хендлерами
студента, старосты и поллером.
"""
import datetime

from common.schedule import (PARITY_EVEN, PARITY_ODD, SUB_CANCEL, is_vuz,
                             week_parity)
from infrastructure.database.repo.requests import RequestsRepo

# Колледж считает чётность на 1 иначе, чем ISO (26.10.2026 — ISO чётная,
# у колледжа нечётная). Дефолт, чтобы вызовы без аргумента не врали.
PARITY_OFFSET = 1


class Slot:
    """Итоговая пара дня — то, что видит студент."""

    __slots__ = ("para", "subject", "teacher", "room", "changed", "action",
                 "comment", "group", "time_note")

    def __init__(self, para: int, subject: str, teacher: str = "", room: str = "",
                 changed: bool = False, action: str = "", comment: str = "",
                 group: str = "", time_note: str = ""):
        self.para = para
        self.subject = subject
        self.teacher = teacher
        self.room = room
        self.changed = changed      # пришло из замены
        self.action = action        # replace | add | ""
        self.comment = comment
        # Время пары, если оно стоит в самой ячейке («с 18.00 до 21.00»).
        # Пять пар колледжа идут не по звонку; без этого поля студент
        # видел время обычной пары и приходил на два часа раньше.
        self.time_note = time_note
        # Группа нужна format_day: по ней выбираются звонки и подпись
        # под парой. У преподавателя вуза слот собирается из base_lesson,
        # и без этого поля день вообще не открывался.
        self.group = group

    def __repr__(self):
        return f"<Slot {self.para} {self.subject}{' (замена)' if self.changed else ''}>"


async def get_day_slots(repo: RequestsRepo, group: str, date: datetime.date,
                        parity_offset: int = PARITY_OFFSET) -> list[Slot]:
    """Итоговое расписание группы на дату."""
    parity = week_parity(date, parity_offset)

    # У вуза своя нумерация недель от якоря. Чётность для пар без списка
    # недель («н.»/«ч.» в файле) тоже вузовская — от этого же счёта.
    # Раньше бралась ISO-чётность со сдвигом PARITY_OFFSET=1: до января
    # она совпадала с вузовской случайно, а с 04.01.2027 расходится и
    # расписание инвертируется — пары показываются в чужую неделю.
    week = None
    if is_vuz(group):
        from tgbot.services import sync_vuz
        anchor = await sync_vuz.get_anchor(repo)
        week = sync_vuz.vuz_week(date, anchor)
        parity = PARITY_EVEN if week % 2 == 0 else PARITY_ODD

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
            # Отменённую пару показываем зачёркнутой, а не выбрасываем.
            # Раньше она молча исчезала: студент видел «Занятий нет 🙌»
            # и не понимал, отменили пару или её никогда не было.
            slots.append(Slot(lesson.para, lesson.subject, lesson.teacher,
                              lesson.room, changed=True, action=SUB_CANCEL,
                              group=group, time_note=getattr(lesson, "time_note", "") or ""))
            continue
        if sub and sub.action in ("replace", "add"):
            slots.append(Slot(lesson.para, sub.subject, sub.teacher, sub.room,
                              changed=True, action=sub.action, comment=sub.comment,
                              group=group))
        else:
            slots.append(Slot(lesson.para, lesson.subject, lesson.teacher, lesson.room,
                              group=group, time_note=getattr(lesson, "time_note", "") or ""))

    # Замена на пару, которой нет в базовом расписании, — это новая пара,
    # а не «добавление». У вуза такие часты: перенос на субботу, разовая
    # консультация. Раньше учитывался только action='add', и такая замена
    # молча пропадала — студент видел пустой день.
    #
    # «Добавить» на пару, которая уже есть в базе, — это фактически замена:
    # второй слот на тот же номер пары создавать нельзя.
    for para, sub in sorted(sub_by_para.items()):
        if sub.action in ("add", "replace") and para not in used:
            slots.append(Slot(para, sub.subject, sub.teacher, sub.room,
                              changed=True, action=sub.action, comment=sub.comment,
                              group=group))

    slots.sort(key=lambda s: s.para)
    return slots
