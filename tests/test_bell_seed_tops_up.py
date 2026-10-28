"""Досыпка звонков доходит до живой базы.

`seed_if_empty` молчал, если в таблице была хоть одна строка. На проде
это значило, что правка DEFAULT_BELL не действует никогда: таблица
заполнена с первого запуска, поэтому новая 6-я пара (обычных дней и
понедельника) до студентов не доходила — карточка показывала заглушку
«пара 6» вместо времени.

Проверено на проде 28.10.2026: в bell_schedule 42 строки, 6-й пары нет.
"""
import datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from common.schedule import format_day
from infrastructure.database.models import Base, BellSchedule
from infrastructure.database.repo.bell_schedule import DEFAULT_BELL
from infrastructure.database.repo.requests import RequestsRepo
from tgbot.services.schedule_layer import Slot

MONDAY = datetime.date(2026, 11, 2)


@pytest.fixture
async def repo():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    pool = async_sessionmaker(engine, expire_on_commit=False)
    async with pool() as session:
        yield RequestsRepo(session)
    await engine.dispose()


async def _rows(repo):
    return (await repo.bell_schedule.session.execute(select(BellSchedule))).scalars().all()


@pytest.mark.asyncio
async def test_partial_table_gets_new_rows(repo):
    """База с устаревшей сеткой догоняет константу."""
    stale = [r for r in DEFAULT_BELL if not (r[0] == "MONDAY" and r[2] == 6)]
    repo.bell_schedule.session.add_all([
        BellSchedule(day_type=d, course_group=c, para=p,
                     start=datetime.time.fromisoformat(s),
                     h1_end=datetime.time.fromisoformat(e1),
                     h2_start=datetime.time.fromisoformat(s2),
                     end=datetime.time.fromisoformat(e2))
        for d, c, p, s, e1, s2, e2 in stale
    ])
    await repo.bell_schedule.session.commit()

    await repo.bell_schedule.seed_if_empty()

    got = {(r.day_type, r.course_group, r.para) for r in await _rows(repo)}
    assert ("MONDAY", "I_IV", 6) in got
    assert ("MONDAY", "II_III", 6) in got


@pytest.mark.asyncio
async def test_existing_rows_are_not_overwritten(repo):
    """Правку админа через редактор досыпка не затирает."""
    repo.bell_schedule.session.add(
        BellSchedule(day_type="MONDAY", course_group="I_IV", para=1,
                     start=datetime.time(8, 0), h1_end=datetime.time(8, 45),
                     h2_start=datetime.time(8, 50), end=datetime.time(9, 35)))
    await repo.bell_schedule.session.commit()

    await repo.bell_schedule.seed_if_empty()

    row = next(r for r in await _rows(repo)
               if (r.day_type, r.course_group, r.para) == ("MONDAY", "I_IV", 1))
    assert row.start == datetime.time(8, 0)


@pytest.mark.asyncio
async def test_second_run_adds_nothing(repo):
    await repo.bell_schedule.seed_if_empty()
    first = len(await _rows(repo))
    await repo.bell_schedule.seed_if_empty()
    assert len(await _rows(repo)) == first


@pytest.mark.asyncio
async def test_sixth_para_has_time_after_top_up(repo):
    """То, ради чего всё: карточка показывает 18:30, а не «пара 6»."""
    stale = [r for r in DEFAULT_BELL if r[2] != 6]
    repo.bell_schedule.session.add_all([
        BellSchedule(day_type=d, course_group=c, para=p,
                     start=datetime.time.fromisoformat(s),
                     h1_end=datetime.time.fromisoformat(e1),
                     h2_start=datetime.time.fromisoformat(s2),
                     end=datetime.time.fromisoformat(e2))
        for d, c, p, s, e1, s2, e2 in stale
    ])
    await repo.bell_schedule.session.commit()

    await repo.bell_schedule.seed_if_empty()
    bell, lunches = await repo.bell_schedule.get_context()

    slot = Slot(para=6, subject="Архивное дело", teacher="Тест Т.Т.", room="101")
    text = format_day(MONDAY, [slot], bell, lunches, meta="group", merge_groups=False)
    assert "18:30" in text and "20:05" in text, text
    assert "пара 6" not in text, text
