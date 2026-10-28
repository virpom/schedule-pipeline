"""Преподаватель вуза не получает предупреждение про сайт колледжа (план 139).

_day_text выбирал источник предупреждения по user.group, а у
преподавателя group пуст всегда. is_vuz(None) -> False, поэтому он
уходил в колледжевую ветку: если лежит сайт колледжа, преподаватель
вуза читал «сайт колледжа не отвечает», хотя его пары приходят из
другого источника.

Теперь для преподавателя источник определяется по группам его пар.
"""
import asyncio
import datetime
from types import SimpleNamespace

from tgbot.handlers import user as user_mod

D = datetime.date(2026, 10, 28)


async def _context(*a, **k):
    return {}, {}


async def _none(*a, **k):
    return None


def _repo(stale_college=False, stale_vuz=False):
    return SimpleNamespace(
        bell_schedule=SimpleNamespace(get_context=_context),
        users=SimpleNamespace(get_group_course_map=_none),
        college_lessons=SimpleNamespace(get_for_group_date=lambda *a: _empty(),
                                        get_for_teacher_date=lambda *a: _empty()),
        schedule_files=SimpleNamespace(get_hash=_none),
        settings=SimpleNamespace(get=_none, get_all=_none),
        snapshots=SimpleNamespace(get_dates_for_group=_empty,
                                  get_dates_for_teacher=_empty),
    )


async def _empty(*a, **k):
    return []


def _user(role="teacher", teacher="Кабышева М.И."):
    return SimpleNamespace(id=1, role=role, group=None, teacher_name=teacher,
                           course=1, bell_detail="brief", subscribed=True)


def _patch(monkeypatch, lessons, calls):
    async def fake_lessons(repo, user, date):
        return lessons

    async def fake_cmap(repo, user):
        return None

    async def is_stale(repo):
        calls.append("college")
        return False

    async def is_stale_vuz(repo):
        calls.append("vuz")
        return False

    monkeypatch.setattr(user_mod, "_user_lessons", fake_lessons)
    monkeypatch.setattr(user_mod, "_course_group_map", fake_cmap)
    monkeypatch.setattr(user_mod, "_day_text_fmt", lambda *a: "текст", raising=False)
    monkeypatch.setattr(user_mod.source_state, "is_stale", is_stale)
    monkeypatch.setattr(user_mod.source_state, "is_stale_vuz", is_stale_vuz)


def test_vuz_teacher_checks_vuz_source(monkeypatch):
    calls = []
    lesson = SimpleNamespace(para=1, subject="Физкультура", group="СА - 26-2@vuz",
                             teacher="Кабышева М.И.", room="", changed=False, action="")
    _patch(monkeypatch, [lesson], calls)
    asyncio.run(user_mod._day_text(_repo(), _user(), D))
    assert calls == ["vuz"], calls


def test_college_teacher_checks_college_source(monkeypatch):
    calls = []
    lesson = SimpleNamespace(para=1, subject="История", group="ДП-26",
                             teacher="Иванов И.И.", room="", changed=False, action="")
    _patch(monkeypatch, [lesson], calls)
    asyncio.run(user_mod._day_text(_repo(), _user(teacher="Иванов И.И."), D))
    assert calls == ["college"], calls


def test_mixed_teacher_uses_college(monkeypatch):
    """Ведёт и колледж, и вуз — предупреждение про колледж уместно."""
    calls = []
    lessons = [SimpleNamespace(para=1, subject="А", group="ДП-26", teacher="Т",
                               room="", changed=False, action=""),
               SimpleNamespace(para=2, subject="Б", group="СА - 26-2@vuz", teacher="Т",
                               room="", changed=False, action="")]
    _patch(monkeypatch, lessons, calls)
    asyncio.run(user_mod._day_text(_repo(), _user(teacher="Т"), D))
    assert calls == ["college"], calls


def test_student_vuz_unchanged(monkeypatch):
    calls = []
    lesson = SimpleNamespace(para=1, subject="А", group="СА - 26-2@vuz", teacher="Т",
                             room="", changed=False, action="")
    _patch(monkeypatch, [lesson], calls)
    u = SimpleNamespace(id=1, role="student", group="СА - 26-2@vuz",
                        teacher_name=None, course=1, bell_detail="brief", subscribed=True)
    asyncio.run(user_mod._day_text(_repo(), u, D))
    assert calls == ["vuz"], calls
