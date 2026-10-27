"""`/setbell` сохраняет перерыв внутри пары.

План 045, баг 1. `upsert` принимал только `start` и `end`, а `h1_end` и
`h2_start` выставлял в `end` — пара становилась сплошным блоком.

Что ломалось:
- экран пары терял «09:00–09:45 / 09:50–10:35» и показывал сплошное;
- у `bell_mode=full` пропадали напоминания о перемене: `bell.py`
  вешает их только при `h1_end != h2_start`.

На проде перерыв есть у 38 пар из 39 — структура реальная, и команда
её уничтожала.

Баг 2 того же плана (сетка вуза) закрыт раньше, в плане 027.
"""
import datetime
import inspect

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from infrastructure.database.models import Base
from infrastructure.database.repo.requests import RequestsRepo
from tgbot.handlers import admin


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
async def test_upsert_keeps_break(repo):
    """Четыре времени — перерыв сохранён как задан."""
    await repo.bell_schedule.upsert(
        "OTHER", "I_IV", 2,
        datetime.time(10, 45), datetime.time(12, 40),
        h1_end=datetime.time(11, 30), h2_start=datetime.time(11, 55))
    bell, _ = await repo.bell_schedule.get_context()
    bs = bell[("OTHER", "I_IV", 2)]
    assert bs.h1_end == datetime.time(11, 30)
    assert bs.h2_start == datetime.time(11, 55)
    assert bs.end == datetime.time(12, 40)


@pytest.mark.asyncio
async def test_upsert_without_break_is_solid(repo):
    """Два времени — сплошная пара, как раньше."""
    await repo.bell_schedule.upsert(
        "OTHER", "I_IV", 1,
        datetime.time(9, 0), datetime.time(10, 35))
    bell, _ = await repo.bell_schedule.get_context()
    bs = bell[("OTHER", "I_IV", 1)]
    assert bs.h1_end == bs.h2_start == datetime.time(10, 35)


@pytest.mark.asyncio
async def test_upsert_updates_break_too(repo):
    """Повторный вызов обновляет и перерыв, а не только края."""
    await repo.bell_schedule.upsert(
        "OTHER", "I_IV", 2,
        datetime.time(10, 45), datetime.time(12, 40),
        h1_end=datetime.time(11, 30), h2_start=datetime.time(11, 55))
    await repo.bell_schedule.upsert(
        "OTHER", "I_IV", 2,
        datetime.time(10, 50), datetime.time(12, 45),
        h1_end=datetime.time(11, 35), h2_start=datetime.time(12, 0))
    bell, _ = await repo.bell_schedule.get_context()
    bs = bell[("OTHER", "I_IV", 2)]
    assert bs.start == datetime.time(10, 50)
    assert bs.h1_end == datetime.time(11, 35)
    assert bs.h2_start == datetime.time(12, 0)


def test_handler_accepts_four_times():
    """Разбор «HH:MM-HH:MM-HH:MM-HH:MM» есть в обработчике."""
    src = inspect.getsource(admin.set_bell)
    assert "len(times) == 4" in src
    assert "h1_end" in src and "h2_start" in src


def test_handler_passes_break_to_upsert():
    src = inspect.getsource(admin.set_bell)
    assert "h1_end=h1_end" in src


def test_handler_validates_break_order():
    """Перерыв должен лежать внутри пары."""
    src = inspect.getsource(admin.set_bell)
    assert "start < h1_end <= h2_start < end" in src


def test_full_screen_renders_break():
    """Экран пары показывает перерыв, когда он есть."""
    from common.schedule import _para_full

    class BS:
        start = datetime.time(9, 0)
        h1_end = datetime.time(9, 45)
        h2_start = datetime.time(9, 50)
        end = datetime.time(10, 35)

    class Solid:
        start = datetime.time(9, 0)
        h1_end = datetime.time(10, 35)
        h2_start = datetime.time(10, 35)
        end = datetime.time(10, 35)

    assert _para_full(BS(), None) == "09:00–09:45 / 09:50–10:35"
    assert _para_full(Solid(), None) == "09:00–10:35"
