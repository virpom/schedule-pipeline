"""Без группы не показываем ложное «Занятий нет» (план 130).

_day_text не проверял, есть ли у человека группа или фамилия. При
user.group is None _user_lessons возвращал пустой список (в таблице нет
строк с group IS NULL), и срабатывала ветка «пар нет»:

    📅 Среда, 28 октября

    Занятий нет 🙌

Это ложь: бот не знает группы, а не расписание пусто. Кнопка дня
отсекает таких через _require_identity, но _day_text зовут ещё из
текстового меню и «на завтра» — там проверки не было.
"""
import asyncio
import datetime
from types import SimpleNamespace

from tgbot.handlers import user as user_mod

D = datetime.date(2026, 10, 28)


async def _empty(*a, **k):
    return {}


async def _empty_list(*a, **k):
    return []


async def _context(*a, **k):
    return {}, {}


def _repo():
    return SimpleNamespace(
        bell_schedule=SimpleNamespace(get_context=_context),
        users=SimpleNamespace(get_group_course_map=_empty),
        college_lessons=SimpleNamespace(get_for_group_date=_empty_list,
                                        get_for_teacher_date=_empty_list),
        schedule_files=SimpleNamespace(get_hash=_empty),
        settings=SimpleNamespace(get=_empty, get_all=_empty),
        snapshots=SimpleNamespace(get_dates_for_group=_empty_list,
                                  get_dates_for_teacher=_empty_list),
    )


def _user(role="student", group=None, teacher=None):
    return SimpleNamespace(id=1, role=role, group=group, teacher_name=teacher,
                           course=1, bell_detail="brief", subscribed=True)


def test_student_without_group_day():
    got = asyncio.run(user_mod._day_text(_repo(), _user(), D))
    assert "Занятий нет" not in got, got
    assert "выбери группу" in got.lower(), got


def test_student_without_group_week():
    got = asyncio.run(user_mod._week_text(_repo(), _user()))
    assert "Занятий нет" not in got, got
    assert "выбери группу" in got.lower(), got


def test_teacher_without_name():
    got = asyncio.run(user_mod._day_text(_repo(), _user(role="teacher"), D))
    assert "Занятий нет" not in got, got


def test_student_with_group_unaffected(monkeypatch):
    """С группой экран дня работает как раньше."""
    async def fake_lessons(repo, user, date):
        return []

    monkeypatch.setattr(user_mod, "_user_lessons", fake_lessons)
    monkeypatch.setattr(user_mod, "_course_group_map", lambda r, u: _none())
    monkeypatch.setattr(user_mod, "format_no_lessons", lambda d: "ПАР НЕТ Сегодня")
    got = asyncio.run(user_mod._day_text(_repo(), _user(group="ДП-26"), D))
    assert "ПАР НЕТ Сегодня" in got, got


async def _none(*a, **k):
    return None
