"""Отмена пары, которой нет в базе, не исчезает (план 093).

get_day_slots обрабатывал отмену только внутри цикла по базовым парам.
Если колледж ставит «НЕТ ПАРЫ» на слот, где пары не было, — а он так
делает, — отмена не попадала никуда: не в slots, не в used.

Живой случай из плана: ДОУ-24, 26.10.2026, четыре отмены подряд, а в
базе по понедельникам только пары 2, 3, 4. Студент видел:

    09:00–09:20  Разговоры о важном 🇷🇺
    2) 11:10–11:55 ...  ❌ отменено
    3) ...

Нумерация начиналась с «2)» — дыра, и не понять, отменили пару или её
никогда не было.
"""
import asyncio
import datetime
from types import SimpleNamespace

from common.schedule import SUB_CANCEL
from tgbot.services.schedule_layer import get_day_slots

D = datetime.date(2026, 11, 9)      # понедельник


def _lesson(para, subject):
    return SimpleNamespace(para=para, subject=subject, teacher="Иванов И.И.",
                           room="каб.1", time_note="", para_end=None)


def _sub(para, action, subject="", comment=""):
    return SimpleNamespace(para=para, action=action, subject=subject,
                           teacher="", room="", comment=comment)


def _repo(base, subs):
    async def get_day(group, weekday, parity, week=None):
        return base

    async def get_for_date(group, date):
        return subs

    return SimpleNamespace(
        base_lessons=SimpleNamespace(get_day=get_day),
        substitutions=SimpleNamespace(get_for_date=get_for_date),
        settings=SimpleNamespace(get=_none, get_all=_empty),
    )


async def _none(*a, **k):
    return None


async def _empty(*a, **k):
    return {}


def test_orphan_cancel_appears():
    got = asyncio.run(get_day_slots(
        _repo([_lesson(2, "Организация"), _lesson(3, "Методика")],
              [_sub(1, SUB_CANCEL, comment="НЕТ ПАРЫ"),
               _sub(2, SUB_CANCEL, comment="НЕТ ПАРЫ")]),
        "ДОУ-24", D, 1))
    paras = [s.para for s in got]
    assert 1 in paras, f"отмена без базы исчезла: {paras}"
    assert 1 not in [s.para for s in got if s.action != SUB_CANCEL]


def test_orphan_cancel_marked():
    got = asyncio.run(get_day_slots(
        _repo([_lesson(2, "Организация")],
              [_sub(1, SUB_CANCEL, comment="НЕТ ПАРЫ")]),
        "ДОУ-24", D, 1))
    slot = next(s for s in got if s.para == 1)
    assert slot.action == SUB_CANCEL, slot.action
    assert slot.changed


def test_no_numbering_gap():
    """Нумерация не должна начинаться с «2)»."""
    got = asyncio.run(get_day_slots(
        _repo([_lesson(2, "Организация"), _lesson(3, "Методика")],
              [_sub(1, SUB_CANCEL, comment="НЕТ ПАРЫ")]),
        "ДОУ-24", D, 1))
    assert [s.para for s in got] == [1, 2, 3]


def test_normal_cancel_still_works():
    """Отмена пары, которая в базе есть, не сломалась."""
    got = asyncio.run(get_day_slots(
        _repo([_lesson(2, "Организация")], [_sub(2, SUB_CANCEL)]),
        "ДОУ-24", D, 1))
    assert len(got) == 1
    assert got[0].action == SUB_CANCEL
    assert got[0].subject == "Организация", "название из базы потеряно"


def test_orphan_add_still_works():
    """Замена на пустой слот — по-прежнему add, а не отмена."""
    got = asyncio.run(get_day_slots(
        _repo([_lesson(2, "Организация")],
              [_sub(5, "add", subject="Консультация")]),
        "ДОУ-24", D, 1))
    assert any(s.para == 5 and s.subject == "Консультация" for s in got)


def test_empty_day_unchanged():
    got = asyncio.run(get_day_slots(_repo([], []), "ДОУ-24", D, 1))
    assert got == []
