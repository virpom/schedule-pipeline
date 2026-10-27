"""Обед приходит по паре из bell_lunch, а не по зашитой двойке.

План 070. В `_tick` границы обеда были жёстко `l.para <= 2 <= para_end`,
а `BellLunch.para` не читался вовсе. В день, где пары начинаются с
третьей (на проде таких групп 9–46 ежедневно), обед не приходил
никому. В базе сейчас только para=2, поэтому дефект латентный — но
зависимость от совпадения с числом в литерале сломается в первый же
день с другим расписанием звонков.
"""
import datetime
import inspect
import types

import pytest

from tgbot.services import bell


class _Pool:
    def __call__(self):
        return self

    async def __aenter__(self):
        return object()

    async def __aexit__(self, *a):
        return False


def _lesson(para, para_end=None, group="ДП-26"):
    return types.SimpleNamespace(
        para=para, para_end=para_end or para, group=group,
        subject="Математика", room="", changed=False, action="", time_note="")


def _lunch(para, start=datetime.time(11, 5), end=datetime.time(11, 35)):
    return types.SimpleNamespace(para=para, position="after",
                                 lunch_start=start, lunch_end=end)


async def _run(lessons, lunch, when):
    """Прогнать _tick и вернуть тексты отправленных сообщений."""
    sent = []

    class _Bell:
        async def get_context(self):
            return {}, {("OTHER", "I_IV"): lunch}

    class _Users:
        async def get_bell_subscribers(self):
            return [types.SimpleNamespace(
                id=42, bell_mode=bell.BELL_FULL, role="student", group="ДП-26",
                course=None, teacher_name=None, bell_detail="brief")]

        async def get_group_course_map(self):
            return {}

    class _Rem:
        async def delete_before(self, d):
            return 0

        async def is_sent(self, *a):
            return False

        async def mark_sent(self, *a):
            return None

    class _CL:
        async def get_for_group_date(self, group, date):
            return lessons

        async def get_for_teacher_date(self, name, date):
            return lessons

    class _Repo:
        bell_schedule = _Bell()
        users = _Users()
        reminders = _Rem()
        college_lessons = _CL()

    real = bell.RequestsRepo
    bell.RequestsRepo = lambda db: _Repo()
    try:
        await bell._tick(None, _Pool(), when)
    finally:
        bell.RequestsRepo = real
    return sent


async def _capture(lessons, lunch, when):
    texts = []

    async def _send(bot, uid, text, **kw):
        texts.append(text)
        return True

    real = bell.send_message
    bell.send_message = _send
    try:
        await _run(lessons, lunch, when)
    finally:
        bell.send_message = real
    return texts


def _src():
    return inspect.getsource(bell._tick)


def test_lunch_para_read_from_db():
    assert 'getattr(lunch, "para"' in _src(), "para обеда не читается"


def test_no_hardcoded_two():
    assert "l.para <= 2 <= " not in _src(), "обед по-прежнему привязан к паре 2"


@pytest.mark.asyncio
async def test_lunch_on_para3_when_day_starts_at_three():
    """Главный сценарий: пары с 3-й — обед должен прийти."""
    when = datetime.datetime(2026, 10, 28, 11, 5, 0)
    texts = await _capture([_lesson(3), _lesson(4)], _lunch(3), when)
    assert any("Обед" in t for t in texts), f"обеда нет: {texts}"


@pytest.mark.asyncio
async def test_no_lunch_when_para_absent():
    """Обед на паре 3, а в день только две пары — не приходит."""
    when = datetime.datetime(2026, 10, 28, 11, 5, 0)
    texts = await _capture([_lesson(1), _lesson(2)], _lunch(3), when)
    assert not any("Обед" in t for t in texts), f"лишний обед: {texts}"


@pytest.mark.asyncio
async def test_no_lunch_on_empty_day():
    when = datetime.datetime(2026, 10, 28, 11, 5, 0)
    texts = await _capture([], _lunch(2), when)
    assert not any("Обед" in t for t in texts)
