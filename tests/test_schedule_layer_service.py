"""Тесты сборки дня из слоёв (сервисный уровень, на фейковом репо)."""
import asyncio
import datetime

from common.schedule import PARITY_EVEN, PARITY_ODD, SUB_ADD, SUB_CANCEL, SUB_REPLACE
from tgbot.services.schedule_layer import get_day_slots


class Row:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class FakeBase:
    def __init__(self, lessons):
        self._lessons = lessons

    async def get_day(self, group, weekday, parity):
        return [l for l in self._lessons
                if l.weekday == weekday and l.week_parity in (parity, "ANY")]


class FakeSubs:
    def __init__(self, subs):
        self._subs = subs

    async def get_for_date(self, group, date):
        return [s for s in self._subs if s.date == date]


class FakeRepo:
    def __init__(self, lessons=(), subs=()):
        self.base_lessons = FakeBase(list(lessons))
        self.substitutions = FakeSubs(list(subs))


def lesson(para, subject, weekday=3, parity=PARITY_ODD, teacher="", room=""):
    return Row(para=para, subject=subject, weekday=weekday, week_parity=parity,
               teacher=teacher, room=room)


def sub(para, date, action, subject="", teacher="", room="", comment=""):
    return Row(para=para, date=date, action=action, subject=subject,
               teacher=teacher, room=room, comment=comment)


# 2026-10-21 — среда, ISO-неделя 43 (нечётная)
WED_ODD = datetime.date(2026, 10, 21)
WED_EVEN = datetime.date(2026, 10, 14)   # среда, неделя 42 (чётная)


def test_base_only():
    repo = FakeRepo([lesson(1, "Математика"), lesson(2, "Физика")])
    slots = asyncio.run(get_day_slots(repo, "ДП-26", WED_ODD))
    assert [(s.para, s.subject) for s in slots] == [(1, "Математика"), (2, "Физика")]
    assert all(not s.changed for s in slots)


def test_parity_filters_out_other_week():
    """Нечётная база не должна показываться в чётную неделю."""
    repo = FakeRepo([lesson(1, "Математика", parity=PARITY_ODD)])
    slots = asyncio.run(get_day_slots(repo, "ДП-26", WED_EVEN))
    assert slots == []


def test_replace_marks_changed():
    repo = FakeRepo([lesson(1, "Математика")],
                    [sub(1, WED_ODD, SUB_REPLACE, "Химия", "Сидоров С.С.")])
    slots = asyncio.run(get_day_slots(repo, "ДП-26", WED_ODD))
    assert len(slots) == 1
    assert slots[0].subject == "Химия"
    assert slots[0].changed is True
    assert slots[0].teacher == "Сидоров С.С."


def test_cancel_removes_base_lesson():
    repo = FakeRepo([lesson(1, "Математика"), lesson(2, "Физика")],
                    [sub(1, WED_ODD, SUB_CANCEL)])
    slots = asyncio.run(get_day_slots(repo, "ДП-26", WED_ODD))
    assert [(s.para, s.subject) for s in slots] == [(2, "Физика")]


def test_add_inserts_without_base():
    repo = FakeRepo([], [sub(3, WED_ODD, SUB_ADD, "История")])
    slots = asyncio.run(get_day_slots(repo, "ДП-26", WED_ODD))
    assert [(s.para, s.subject, s.changed) for s in slots] == [(3, "История", True)]


def test_cancel_all_is_empty_day():
    repo = FakeRepo([lesson(1, "Математика")], [sub(1, WED_ODD, SUB_CANCEL)])
    assert asyncio.run(get_day_slots(repo, "ДП-26", WED_ODD)) == []


def test_slots_sorted_by_para():
    repo = FakeRepo([lesson(3, "Третья"), lesson(1, "Первая")],
                    [sub(2, WED_ODD, SUB_ADD, "Вторая")])
    slots = asyncio.run(get_day_slots(repo, "ДП-26", WED_ODD))
    assert [s.para for s in slots] == [1, 2, 3]


def test_other_date_substitution_ignored():
    other = datetime.date(2026, 10, 22)
    repo = FakeRepo([lesson(1, "Математика")], [sub(1, other, SUB_REPLACE, "Химия")])
    slots = asyncio.run(get_day_slots(repo, "ДП-26", WED_ODD))
    assert slots[0].subject == "Математика"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok  {name}")
    print("OK")
