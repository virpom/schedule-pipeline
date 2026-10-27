"""Ночью данные не считаются устаревшими.

План 049. Поллер намеренно спит с 23:00 до 07:00, а порог устаревания
был 30 минут. Значит с 23:27 до 07:05 — треть суток каждую ночь —
любой экран показывал «сайт не отвечает», хотя сайт жив.

Проверено на проде: ключей night_start/night_end в базе нет, работают
дефолты 23:00–07:00, то есть предупреждение включалось каждую ночь.
"""
import datetime

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from infrastructure.database.models import Base
from infrastructure.database.repo.requests import RequestsRepo
from tgbot.services import source_state
from tgbot.services.source_state import _night_length, in_night


@pytest.fixture
async def repo():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    pool = async_sessionmaker(engine, expire_on_commit=False)
    async with pool() as session:
        yield RequestsRepo(session)
    await engine.dispose()


def test_in_night_inside():
    assert in_night(datetime.datetime(2026, 10, 27, 23, 30), "23:00", "07:00")


def test_in_night_after_midnight():
    assert in_night(datetime.datetime(2026, 10, 28, 0, 30), "23:00", "07:00")
    assert in_night(datetime.datetime(2026, 10, 28, 6, 59), "23:00", "07:00")


def test_in_night_boundaries():
    """Полуинтервал [start, end): 07:00 уже не ночь."""
    assert not in_night(datetime.datetime(2026, 10, 28, 7, 0), "23:00", "07:00")
    assert in_night(datetime.datetime(2026, 10, 27, 23, 0), "23:00", "07:00")
    assert not in_night(datetime.datetime(2026, 10, 27, 22, 59), "23:00", "07:00")
    assert not in_night(datetime.datetime(2026, 10, 27, 12, 0), "23:00", "07:00")


def test_in_night_empty_or_equal():
    assert not in_night(datetime.datetime(2026, 10, 27, 23, 30), "", "")
    assert not in_night(datetime.datetime(2026, 10, 27, 23, 30), "23:00", "23:00")


def test_in_night_aware_rejected():
    """Часы с поясом не роняют поллер (TypeError на сравнении)."""
    assert not in_night(datetime.datetime(2026, 10, 27, 23, 30),
                        "23:00+03:00", "07:00")


def test_night_length_eight_hours():
    got = _night_length({"night_start": "23:00", "night_end": "07:00"})
    assert got == datetime.timedelta(hours=8)


def test_night_length_broken():
    assert _night_length({}) == datetime.timedelta()
    assert _night_length({"night_start": "кривое", "night_end": "07:00"}) \
        == datetime.timedelta()


@pytest.mark.asyncio
async def test_not_stale_during_night(repo, monkeypatch):
    """Успех был 3 часа назад, сейчас ночь — не устарело."""
    now = datetime.datetime(2026, 10, 28, 2, 0)
    monkeypatch.setattr(source_state.datetime, "datetime",
                        type("DT", (datetime.datetime,),
                             {"now": staticmethod(lambda: now)}))
    await repo.settings.set(source_state.LAST_OK,
                            (now - datetime.timedelta(hours=3)).isoformat())
    assert await source_state.is_stale(repo) is False


@pytest.mark.asyncio
async def test_stale_during_day(repo, monkeypatch):
    """Тот же трёхчасовой разрыв днём — устарело."""
    now = datetime.datetime(2026, 10, 28, 14, 0)
    monkeypatch.setattr(source_state.datetime, "datetime",
                        type("DT", (datetime.datetime,),
                             {"now": staticmethod(lambda: now)}))
    await repo.settings.set(source_state.LAST_OK,
                            (now - datetime.timedelta(hours=3)).isoformat())
    assert await source_state.is_stale(repo) is True


@pytest.mark.asyncio
async def test_stale_at_night_if_really_old(repo, monkeypatch):
    """Ночь не спасает от настоящего сбоя длиной больше суток."""
    now = datetime.datetime(2026, 10, 28, 2, 0)
    monkeypatch.setattr(source_state.datetime, "datetime",
                        type("DT", (datetime.datetime,),
                             {"now": staticmethod(lambda: now)}))
    await repo.settings.set(source_state.LAST_OK,
                            (now - datetime.timedelta(hours=20)).isoformat())
    assert await source_state.is_stale(repo) is True


@pytest.mark.asyncio
async def test_vuz_also_night_aware(repo, monkeypatch):
    now = datetime.datetime(2026, 10, 28, 2, 0)
    monkeypatch.setattr(source_state.datetime, "datetime",
                        type("DT", (datetime.datetime,),
                             {"now": staticmethod(lambda: now)}))
    await repo.settings.set(source_state.LAST_OK_VUZ,
                            (now - datetime.timedelta(hours=3)).isoformat())
    assert await source_state.is_stale_vuz(repo) is False
