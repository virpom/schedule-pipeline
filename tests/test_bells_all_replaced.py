"""Строка ALL из файла заменяет константу, а не падает на UNIQUE.

План 033 вскрыл это на проде в 20:56 после деплоя:

  sqlite3.IntegrityError: UNIQUE constraint failed:
  bell_schedule.day_type, bell_schedule.course_group, bell_schedule.para
  [parameters: ('MONDAY', 'ALL', 0, ...)]

`replace_bells` держал `ALL` в списке `keep`, то есть сохранял старую
строку «Разговоров» из `DEFAULT_BELL`. Пока «Разговоры» из файла не
разбирались, конфликта не было — файл не давал `ALL`. Как только
парсер стал их отдавать, старая и новая строки сошлись на одном ключе.

Итог был не косметический: `sync_once` падал целиком, звонки не
обновлялись, админу уходила тревога «Не обновились файлы: звонки».
"""
import datetime

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from infrastructure.database.models import Base, BellSchedule
from infrastructure.database.repo.requests import RequestsRepo
from tgbot.services.sync_eios import replace_bells


class Row:
    def __init__(self, **kw):
        self.__dict__.update(kw)


@pytest.fixture
async def repo():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    pool = async_sessionmaker(engine, expire_on_commit=False)
    async with pool() as session:
        yield RequestsRepo(session)
    await engine.dispose()


@pytest.mark.asyncio
async def test_all_from_file_replaces_constant(repo):
    """Старая константа ALL не мешает вставить новую из файла."""
    t = datetime.time
    repo.session.add(BellSchedule(
        day_type="MONDAY", course_group="ALL", para=0,
        start=t(8, 0), h1_end=t(8, 15), h2_start=t(8, 20), end=t(8, 30)))
    await repo.session.commit()

    slot = Row(day_type="MONDAY", course_group="ALL", para=0,
               start=t(9, 0), end1=t(9, 20), start2=t(9, 0), end2=t(9, 20))
    await replace_bells(repo, [slot])

    rows = (await repo.session.execute(
        __import__("sqlalchemy").select(BellSchedule))).scalars().all()
    rov = [r for r in rows if r.course_group == "ALL" and r.para == 0]
    assert len(rov) == 1, f"строк ALL/0: {len(rov)}"
    assert rov[0].start == t(9, 0), "осталась старая константа 08:00"
    assert rov[0].end == t(9, 20)


@pytest.mark.asyncio
async def test_vuz_still_kept(repo):
    """Сетка вуза по-прежнему выживает — она не из файлов колледжа."""
    t = datetime.time
    repo.session.add(BellSchedule(
        day_type="OTHER", course_group="VUZ", para=1,
        start=t(8, 40), h1_end=t(9, 25), h2_start=t(9, 35), end=t(10, 10)))
    await repo.session.commit()

    slot = Row(day_type="OTHER", course_group="II_III", para=1,
               start=t(11, 0), end1=t(11, 45), start2=t(11, 55), end2=t(12, 30))
    await replace_bells(repo, [slot])

    rows = (await repo.session.execute(
        __import__("sqlalchemy").select(BellSchedule))).scalars().all()
    assert any(r.course_group == "VUZ" for r in rows)


@pytest.mark.asyncio
async def test_no_duplicate_on_repeat(repo):
    """Повторный проход с тем же ALL не плодит строк."""
    t = datetime.time
    slot = Row(day_type="MONDAY", course_group="ALL", para=0,
               start=t(9, 0), end1=t(9, 20), start2=t(9, 0), end2=t(9, 20))
    await replace_bells(repo, [slot])
    await replace_bells(repo, [slot])

    rows = (await repo.session.execute(
        __import__("sqlalchemy").select(BellSchedule))).scalars().all()
    assert len([r for r in rows if r.course_group == "ALL"]) == 1
