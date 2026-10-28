"""Неделя преподавателя склеивает поток так же, как день (076 / 147).

_merge_groups склеивает пары одного преподавателя на один слот: шесть
групп на физкультуре — одна пара, а не шесть строк. Экран дня флаг
передавал, format_week параметра не имел вовсе, и преподаватель видел
одну и ту же пару по-разному на двух экранах.
"""
import datetime
import inspect

from common.schedule import format_week
from tgbot.handlers import user as user_mod
from tgbot.services.schedule_layer import Slot


def test_format_week_has_merge_flag():
    assert "merge_groups" in inspect.signature(format_week).parameters


def test_week_passes_flag_to_format_day():
    body = inspect.getsource(format_week)
    assert "merge_groups=merge_groups" in body


def test_week_text_sets_flag_for_teacher():
    body = inspect.getsource(user_mod._week_text)
    assert "_is_teacher(user)" in body, "неделя не передаёт флаг"


def _entries():
    d = datetime.date(2026, 11, 9)
    lessons = [
        Slot(1, "Физическая культура", "Сидоров С.С.", "спортзал", group=g)
        for g in ("ДП-26", "ЭК-26", "ПСО-26", "СА-26", "ТЭ-26", "ЭО-26")
    ]
    return [(d, lessons)]


def test_merge_collapses_stream():
    """Шесть групп одного преподавателя — одна строка."""
    merged = format_week(_entries(), {}, {}, meta="group", merge_groups=True)
    plain = format_week(_entries(), {}, {}, meta="group")
    assert merged.count("Физическая культура") == 1, merged
    assert plain.count("Физическая культура") == 6, plain


def test_merge_off_by_default():
    """Для студента поведение прежнее."""
    assert inspect.signature(format_week).parameters["merge_groups"].default is False
