"""Спаренная пара печатается одной строкой.

План 056. `format_day` крутил цикл по `para..para_end` и печатал строку
на каждую пару. Для склеенного занятия это давало два блока с перерывом
между ними — студент читал их как разные предметы.
"""
import datetime

from common.schedule import DETAIL_BRIEF, DETAIL_FULL, format_day
from tgbot.services.schedule_layer import Slot


class _BS:
    def __init__(self, start, h1_end, h2_start, end):
        self.start, self.h1_end, self.h2_start, self.end = start, h1_end, h2_start, end


T = datetime.time
SAT = datetime.date(2026, 11, 7)          # суббота → day_type OTHER
BELL = {
    ("OTHER", "I_IV", 1): _BS(T(9, 0), T(9, 45), T(9, 50), T(10, 35)),
    ("OTHER", "I_IV", 2): _BS(T(10, 45), T(11, 30), T(11, 55), T(12, 40)),
    ("OTHER", "I_IV", 3): _BS(T(12, 50), T(13, 35), T(13, 40), T(14, 25)),
}
CG = {"ДП-26": "I_IV"}


def _render(slots, detail=DETAIL_FULL):
    return format_day(SAT, slots, BELL, {}, detail, group_course_group=CG)


def test_paired_lesson_one_line():
    slots = [Slot(1, "Организация документооборота", "Харькова Д.А.",
                  group="ДП-26", para_end=2)]
    text = _render(slots)
    assert "1–2)" in text, text
    assert "2)" not in text.replace("1–2)", ""), "вторая строка не убрана"


def test_paired_lesson_spans_time():
    """Время — от начала первой пары до конца второй."""
    slots = [Slot(1, "Организация документооборота", "Харькова Д.А.",
                  group="ДП-26", para_end=2)]
    text = _render(slots)
    assert "09:00–12:40" in text, text


def test_paired_then_single():
    """Соседняя одиночная пара печатается своим номером."""
    slots = [
        Slot(1, "Организация документооборота", "Харькова Д.А.",
             group="ДП-26", para_end=2),
        Slot(3, "Информационные технологии", "Харькова Д.А.", group="ДП-26"),
    ]
    text = _render(slots)
    assert "1–2)" in text
    assert "3)" in text
    assert text.count("Организация документооборота") == 1


def test_single_lesson_unchanged():
    """Обычная пара печатается как раньше."""
    slots = [Slot(3, "Информационные технологии", "Харькова Д.А.",
                  group="ДП-26")]
    text = _render(slots)
    assert "3) <b>12:50–13:35 / 13:40–14:25</b>" in text, text


def test_brief_paired_still_one_line():
    slots = [Slot(1, "Организация документооборота", "Харькова Д.А.",
                  group="ДП-26", para_end=2)]
    text = _render(slots, DETAIL_BRIEF)
    assert "1–2)" in text
    assert text.count("Организация") == 1


def test_three_para_block():
    slots = [Slot(1, "Тема", "Иванов И.И.", group="ДП-26", para_end=3)]
    text = _render(slots)
    assert "1–3)" in text, text
