"""Прошедшие дни не копятся в college_lesson.

План 056, вариант А. Материализация идёт только вперёд (14 дней), так
что прошедшие даты не перезаписываются никогда и остаются навсегда.
На проде 27.10 было 1434 строки из 4359 — треть таблицы, и число
растёт каждый день.

История прошедших дней уже лежит в `day_snapshot` (1690 строк),
поэтому строки в `college_lesson` за прошлые даты мёртвые.

Чистим раз в сутки по образцу `bell_reminder`. Строго `<`, не `<=`:
сегодняшние пары нужны весь день — студент открывает расписание после
последней пары.
"""
import datetime
import inspect

from tgbot.services import bell, poller


def test_delete_before_exists():
    from infrastructure.database.repo.college_lesson import CollegeLessonRepo
    assert hasattr(CollegeLessonRepo, "delete_before")


def test_delete_before_is_strict():
    """`<`, а не `<=` — сегодняшние пары не трогаем."""
    from infrastructure.database.repo.college_lesson import CollegeLessonRepo
    src = inspect.getsource(CollegeLessonRepo.delete_before)
    assert "CollegeLesson.date < date" in src, "не строгое неравенство"
    assert "CollegeLesson.date <=" not in src


def test_delete_before_commits():
    from infrastructure.database.repo.college_lesson import CollegeLessonRepo
    src = inspect.getsource(CollegeLessonRepo.delete_before)
    assert "commit()" in src, "изменение не сохраняется"
    assert "rowcount" in src, "нечего логировать"


def test_purge_once_per_day():
    """В сутки один DELETE, а не на каждом проходе поллера."""
    poller._purge["date"] = None
    calls = []

    class _Subs:
        @staticmethod
        async def delete_before(d):
            return 0

    class _Repo:
        class college_lessons:
            @staticmethod
            async def delete_before(d):
                calls.append(d)
                return 5

        substitutions = _Subs()

    real = poller.RequestsRepo
    poller.RequestsRepo = lambda db: _Repo()
    today = datetime.date(2026, 10, 28)
    try:
        import asyncio
        for _ in range(3):
            asyncio.run(poller._purge_past(_FakePool(), today))
    finally:
        poller.RequestsRepo = real
        poller._purge["date"] = None

    assert calls == [today], f"чистка не раз в сутки: {calls}"


class _FakePool:
    def __call__(self):
        return self

    async def __aenter__(self):
        return object()

    async def __aexit__(self, *a):
        return False


def test_purge_resets_on_failure():
    """Сбой не должен блокировать чистку навсегда."""
    poller._purge["date"] = None

    class _Repo:
        class college_lessons:
            @staticmethod
            async def delete_before(d):
                raise RuntimeError("locked")

    real = poller.RequestsRepo
    poller.RequestsRepo = lambda db: _Repo()
    try:
        import asyncio
        asyncio.run(poller._purge_past(_FakePool()))
    finally:
        poller.RequestsRepo = real
    assert poller._purge["date"] is None, "после сбоя день отмечен обработанным"


def test_poller_calls_purge():
    assert "_purge_past" in inspect.getsource(poller.poller_loop)


def test_same_pattern_as_bell():
    """Образец один и тот же — не два разных подхода к чистке."""
    assert isinstance(bell._purge, dict)
    assert "date" in bell._purge
    assert isinstance(poller._purge, dict)
