"""«Неделя» показывает дни без пар (план 095).

_week_text собирал entries из by_date, а туда попадали только дни, где
есть хотя бы одна пара. День без пар в entries не попадал вовсе, и
студент не отличал «в этот день пар нет» от «этот день не показали».

format_week честно рисует то, что дали, а format_day на пустом списке
сам пишет «Занятий нет» — не хватало только передать все семь дней.
"""
import asyncio
import datetime
from types import SimpleNamespace

from tgbot.handlers import user as user_mod
from tgbot.services.schedule_layer import Slot


async def _empty(*a, **k):
    return {}


def _day(d):
    return datetime.date.today() + datetime.timedelta(days=d)


def _run(lessons, monkeypatch):
    async def fake_context():
        return {}, {}

    async def fake_gcg(repo, user):
        return None

    async def fake_range(repo, user, start, end):
        return lessons

    monkeypatch.setattr(user_mod, "_user_lessons_range", fake_range)
    monkeypatch.setattr(user_mod, "_course_group_map", fake_gcg)
    monkeypatch.setattr(user_mod, "format_week",
                        lambda entries, *a, **k:
                        "ДНЕЙ:" + str(len(entries)) + "|" + ",".join(
                            f"{d.day}:{len(v)}" for d, v in entries))
    repo = SimpleNamespace(bell_schedule=SimpleNamespace(get_context=fake_context),
                           settings=SimpleNamespace(get=_empty, get_all=_empty))
    user = SimpleNamespace(id=1, role="student", group="ДП-26", course=1,
                           teacher_name=None, bell_detail="brief")
    return asyncio.run(user_mod._week_text(repo, user))


def test_all_seven_days_passed(monkeypatch):
    got = _run([Slot(1, "Математика", "Иванов И.И.", "101", date=_day(0))], monkeypatch)
    assert "ДНЕЙ:7" in got, got


def test_empty_days_have_zero_lessons(monkeypatch):
    got = _run([Slot(1, "Математика", "Иванов И.И.", "101", date=_day(0))], monkeypatch)
    parts = got.split("|")[1].split(",")
    assert parts[0].endswith(":1"), parts
    assert all(p.endswith(":0") for p in parts[1:]), parts


def test_empty_week_still_seven(monkeypatch):
    got = _run([], monkeypatch)
    assert "ДНЕЙ:7" in got, got


def test_days_in_order(monkeypatch):
    got = _run([Slot(1, "Х", "И", "1", date=_day(3))], monkeypatch)
    days = [int(p.split(":")[0]) for p in got.split("|")[1].split(",")]
    assert days == [(_day(i)).day for i in range(7)], days
