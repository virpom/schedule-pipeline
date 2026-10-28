"""День из одних отмен показывает «Ближайшее» (план 092).

_day_text делил вывод по одному признаку — есть ли слоты. Блок
«Ближайшее» стоял только в ветке else, то есть когда слотов нет вовсе.

Но get_day_slots для отменённой пары возвращает слот с action=SUB_CANCEL,
и это правильно: студент видит зачёркнутую строку, а не «Занятий нет».
Значит если все пары дня отменены, lessons непуст, ветка if, и
«Ближайшее» пропадает — при том что фактически пар нет и знать, когда
они будут, самое нужное.

На 26.10 таких групп было четыре (ДОУ-24, ПСО-23, ЭК-24, ЮР-24А).
Сейчас на проде таких дней нет — дефект латентный, но полная отмена
дня штатная ситуация.
"""
import asyncio
import datetime
from types import SimpleNamespace

from tgbot.handlers import user as user_mod
from tgbot.services.schedule_layer import Slot


D = datetime.date(2026, 11, 9)


def _slot(para, subject, action=""):
    return Slot(para, subject, "Иванов И.И.", "каб.1", action=action)


def _user():
    return SimpleNamespace(id=1, role="student", group="ДП-26", course=1,
                           teacher_name=None, bell_detail="brief")


def _run(day_lessons, next_lessons, monkeypatch):
    async def fake_user_lessons(repo, user, date):
        if date == D:
            return day_lessons
        if date == D + datetime.timedelta(days=1):
            return next_lessons
        return []

    async def fake_context():
        return {}, {}

    async def fake_gcg(repo, user):
        return None

    monkeypatch.setattr(user_mod, "_user_lessons", fake_user_lessons)
    monkeypatch.setattr(user_mod, "_course_group_map", fake_gcg)
    monkeypatch.setattr(user_mod, "_fmt",
                        lambda user, date, lessons, bell, lunches, gcg:
                        "ПАРЫ:" + ",".join(l.subject for l in lessons))

    return asyncio.run(user_mod._day_text(_repo(fake_context), _user(), D))


async def _none(*a, **k):
    return None


async def _empty(*a, **k):
    return {}


def _repo(get_context):
    return SimpleNamespace(
        bell_schedule=SimpleNamespace(get_context=get_context),
        schedule_files=SimpleNamespace(get_hash=_none),
        settings=SimpleNamespace(get_all=_empty, get=_none),
    )


def test_all_cancelled_shows_nearest(monkeypatch):
    got = _run([_slot(1, "История", action="cancel"),
                _slot(2, "Право", action="cancel")],
               [_slot(1, "Химия")], monkeypatch)
    assert "Ближайшее" in got, got
    assert "Химия" in got, got


def test_normal_day_has_no_nearest(monkeypatch):
    """Активные пары есть — «Ближайшее» не нужно."""
    got = _run([_slot(1, "История")], [_slot(1, "Химия")], monkeypatch)
    assert "Ближайшее" not in got, got


def test_empty_day_still_shows_nearest(monkeypatch):
    """Старое поведение не сломали."""
    got = _run([], [_slot(1, "Химия")], monkeypatch)
    assert "Ближайшее" in got, got


def test_nearest_skips_fully_cancelled_day(monkeypatch):
    """Ближайший день, где тоже всё отменено, — не «ближайшее»."""
    async def fake_user_lessons(repo, user, date):
        if date == D:
            return [_slot(1, "История", action="cancel")]
        if date == D + datetime.timedelta(days=1):
            return [_slot(1, "Химия", action="cancel")]
        if date == D + datetime.timedelta(days=2):
            return [_slot(1, "Физика")]
        return []

    async def fake_context():
        return {}, {}

    async def fake_gcg(repo, user):
        return None

    monkeypatch.setattr(user_mod, "_user_lessons", fake_user_lessons)
    monkeypatch.setattr(user_mod, "_course_group_map", fake_gcg)
    monkeypatch.setattr(user_mod, "_fmt",
                        lambda user, date, lessons, bell, lunches, gcg:
                        "ПАРЫ:" + ",".join(l.subject for l in lessons))
    got = asyncio.run(user_mod._day_text(_repo(fake_context), _user(), D))
    assert "Физика" in got, got
    assert "Химия" not in got, got


def test_cancelled_rows_still_shown(monkeypatch):
    """Отменённые пары не выбросили — их видно зачёркнутыми."""
    got = _run([_slot(1, "История", action="cancel")], [_slot(1, "Химия")], monkeypatch)
    assert "История" in got, got
