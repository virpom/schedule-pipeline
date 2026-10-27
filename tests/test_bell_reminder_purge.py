"""Старые отметки звонков удаляются раз в сутки.

План 152. `bell_reminder` росла линейно: 456 строк на проде, из них 60%
за прошлые дни. `is_sent` смотрит только сегодняшнюю дату, так что
вчерашние строки мёртвые и повториться не могут.
"""
import datetime
import inspect

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from infrastructure.database.models import Base
from infrastructure.database.repo.requests import RequestsRepo
from tgbot.services import bell

D1 = datetime.date(2026, 10, 26)
D2 = datetime.date(2026, 10, 27)


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
async def test_delete_before_removes_old(repo):
    await repo.reminders.mark_sent(1, D1, "p1")
    await repo.reminders.mark_sent(2, D2, "p1")
    removed = await repo.reminders.delete_before(D2)
    assert removed == 1
    assert not await repo.reminders.is_sent(1, D1, "p1")
    assert await repo.reminders.is_sent(2, D2, "p1")


@pytest.mark.asyncio
async def test_today_never_deleted(repo):
    """Строго `<`: иначе перезапуск в течение дня даст повторные звонки."""
    await repo.reminders.mark_sent(1, D2, "p1")
    removed = await repo.reminders.delete_before(D2)
    assert removed == 0
    assert await repo.reminders.is_sent(1, D2, "p1")


@pytest.mark.asyncio
async def test_mark_sent_still_dedupes(repo):
    await repo.reminders.mark_sent(1, D2, "p1")
    await repo.reminders.mark_sent(1, D2, "p1")
    assert await repo.reminders.is_sent(1, D2, "p1")


def test_purge_called_in_tick():
    src = inspect.getsource(bell._tick)
    assert "delete_before" in src, "уборка не вызывается"


def test_purge_once_per_day():
    """Не каждый тик: `_tick` крутится раз в 30 секунд."""
    src = inspect.getsource(bell._tick)
    code = "\n".join(line.split("#", 1)[0] for line in src.splitlines())
    guard = code.split("delete_before")[0]
    assert 'today != _purge["date"]' in guard, "нет защиты от повтора"
