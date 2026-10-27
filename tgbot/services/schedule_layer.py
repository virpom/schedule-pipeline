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
                 "comment", "group", "time_note", "para_end")

    def __init__(self, para: int, subject: str, teacher: str = "", room: str = "",
                 changed: bool = False, action: str = "", comment: str = "",
                 group: str = "", time_note: str = "", para_end: int | None = None):
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
        # Последняя пара занятия. Спаренные пары (одна тема на два часа)
        # в файле идут двумя строками подряд; без склейки студент видел
        # два занятия с перерывом между ними вместо одного.
        self.para_end = para_end or para
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
    return _join_paired(slots)


def _join_paired(slots: list[Slot]) -> list[Slot]:
    """Склеить спаренные пары: одна тема на два часа подряд.

    В файле колледжа такая пара идёт двумя строками с одинаковым
    предметом и преподавателем (23 случая из 704). Без склейки студент
    видел два занятия с перерывом вместо одного блока: например
    «1) 09:00–10:35 … 2) 10:45–12:40 …» одной темы.

    Склеиваем только пары, идущие вплотную (para и para+1) с тем же
    предметом и преподавателем. Замены и отмены не трогаем: у них своя
    семантика, и склейка через границу правки спрятала бы её.
    """
    out: list[Slot] = []
    for slot in slots:
        prev = out[-1] if out else None
        same = (
            prev is not None
            and not slot.changed and not prev.changed
            and slot.para == prev.para_end + 1
            and slot.subject == prev.subject
            and slot.teacher == prev.teacher
        )
        if same:
            prev.para_end = slot.para
            continue
        out.append(slot)
    return out
