"""«🆕 Новое расписание» отличается от «🔄 Изменилось».

План 055. Признак «новое» считался как `had_lessons == 0` — общее число
пар во **всей** таблице `college_lesson`, без привязки к дате. На
непустой базе (3927 строк на проде) это условие неверно никогда, значит
студент вместо «🆕 Новое расписание» всегда получал «🔄 Изменилось» —
даже в первый день семестра, когда расписание появляется впервые.

Правильный вопрос: была ли эта дата в базе ДО материализации.
`digest_by_date()` уже снимается до неё, так что отдельный запрос не
нужен.
"""
import datetime

import pytest

from infrastructure.database.repo.college_lesson import CollegeLessonRepo
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from infrastructure.database.models import Base


@pytest.fixture
async def repo():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    pool = async_sessionmaker(engine, expire_on_commit=False)
    async with pool() as session:
        yield CollegeLessonRepo(session)
    await engine.dispose()


def lesson(date, group="ДП-26", para=1):
    """replace_date принимает dict, а не модель."""
    return {"date": date, "group": group, "para": para, "para_end": para,
            "subject": "Физика", "teacher": "Иванов И.И."}


def test_new_day_is_absent_from_digest_before_materialize(repo):
    """Дата, которой не было до материализации, — новая.

    Ровно это и должен спрашивать poller вместо `had_lessons == 0`.
    """
    import asyncio
    today = datetime.date(2026, 10, 27)
    tomorrow = today + datetime.timedelta(days=1)

    async def scenario():
        await repo.replace_date(today, [lesson(today)])
        before = await repo.digest_by_date()
        # Материализация добавила завтрашний день.
        await repo.replace_date(tomorrow, [lesson(tomorrow)])
        after = await repo.digest_by_date()
        return before, after

    before, after = asyncio.run(scenario())
    assert today in before, "сегодняшняя дата была в базе"
    assert tomorrow not in before, "завтрашней даты не было"
    # Признак «новое» — именно отсутствие даты в before.
    assert (today not in before) is False
    assert (tomorrow not in before) is True


def test_existing_day_is_not_new(repo):
    """Повторная материализация не делает день «новым»."""
    import asyncio
    day = datetime.date(2026, 10, 27)

    async def scenario():
        await repo.replace_date(day, [lesson(day)])
        before = await repo.digest_by_date()
        await repo.replace_date(day, [lesson(day, para=2)])
        return before

    before = asyncio.run(scenario())
    assert day in before


def test_digest_is_empty_on_empty_base(repo):
    """Пустая база: все дни новые — прежнее поведение сохранено."""
    import asyncio
    assert asyncio.run(repo.digest_by_date()) == {}


def test_digest_is_taken_before_materialize_in_poller():
    """В poller `before` снимается до вызова materialize.

    Иначе сравнение бессмысленно: после материализации все дни на месте.
    """
    import inspect
    from tgbot.services import poller

    src = inspect.getsource(poller.poll_once)
    i_before = src.index("digest_by_date")
    i_materialize = src.index("materialize(repo)")
    assert i_before < i_materialize, "before снимается после материализации"
    code = "\n".join(line.split("#", 1)[0] for line in src.splitlines())
    assert "had_lessons" not in code, "остался старый признак по всей таблице"
