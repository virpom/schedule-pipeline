"""Архив `day_snapshot` читается, а не только пишется.

План 039. `snapshot_past_days` каждый час сохранял прошедшие дни, но
читать их было некому: «История» строилась только по `college_lesson`.
На проде 20–22.10 были в архиве и невидимы студенту.

Заодно в `save` не хватало четырёх полей из восьми. Главное — `action`:
`get_day_slots` для отменённой пары кладёт в слот базовые
`subject`/`teacher`, а признак держит в `action`. Без него отмена при
чтении архива выглядела бы как состоявшаяся пара.
"""
import datetime

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from infrastructure.database.models import Base
from infrastructure.database.repo.requests import RequestsRepo
from tgbot.services import notify_edits


@pytest.fixture
async def repo():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    pool = async_sessionmaker(engine, expire_on_commit=False)
    async with pool() as session:
        yield RequestsRepo(session)
    await engine.dispose()


class _Slot:
    def __init__(self, para, subject, **kw):
        self.para = para
        self.subject = subject
        self.teacher = kw.get("teacher", "")
        self.room = kw.get("room", "")
        self.changed = kw.get("changed", False)
        self.action = kw.get("action", "")
        self.comment = kw.get("comment", "")
        self.time_note = kw.get("time_note", "")
        self.para_end = kw.get("para_end", para)


@pytest.mark.asyncio
async def test_snapshot_roundtrip(repo):
    """Сохранённый день читается обратно."""
    date = datetime.date(2026, 10, 20)
    await repo.snapshots.save(date, "ДП-26", [_Slot(2, "Деловая культура")])
    rows = await repo.snapshots.get(date, "ДП-26")
    assert rows and rows[0]["subject"] == "Деловая культура"


@pytest.mark.asyncio
async def test_cancel_survives_roundtrip(repo):
    """Отмена не превращается в состоявшуюся пару."""
    date = datetime.date(2026, 10, 20)
    await repo.snapshots.save(
        date, "ДП-26",
        [_Slot(3, "Архивное дело", changed=True, action="cancel")])
    rows = await repo.snapshots.get(date, "ДП-26")
    assert rows[0]["action"] == "cancel", "признак отмены потерян"
    assert rows[0]["changed"] is True


@pytest.mark.asyncio
async def test_comment_survives_roundtrip(repo):
    date = datetime.date(2026, 10, 20)
    await repo.snapshots.save(
        date, "ДП-26", [_Slot(4, "Физкультура", comment="перенос в зал")])
    rows = await repo.snapshots.get(date, "ДП-26")
    assert rows[0]["comment"] == "перенос в зал"


@pytest.mark.asyncio
async def test_empty_day_is_saved(repo):
    """Пустой день тоже сохраняется: «пар не было» ≠ «бот не работал»."""
    date = datetime.date(2026, 10, 20)
    await repo.snapshots.save(date, "ДП-26", [])
    assert await repo.snapshots.exists(date, "ДП-26")
    assert await repo.snapshots.get(date, "ДП-26") == []


@pytest.mark.asyncio
async def test_get_dates_for_group(repo):
    """Архив отдаёт свои даты — их подмешивает «История»."""
    for d in (datetime.date(2026, 10, 20), datetime.date(2026, 10, 21)):
        await repo.snapshots.save(d, "ДП-26", [_Slot(1, "Математика")])
    await repo.snapshots.save(datetime.date(2026, 10, 21), "ЭК-25",
                              [_Slot(1, "Право")])
    dates = await repo.snapshots.get_dates_for_group("ДП-26")
    assert dates == [datetime.date(2026, 10, 21), datetime.date(2026, 10, 20)]


@pytest.mark.asyncio
async def test_missing_snapshot_is_none(repo):
    assert await repo.snapshots.get(datetime.date(2026, 10, 20), "нет") is None


@pytest.mark.asyncio
async def test_broken_payload_does_not_crash(repo):
    """Битый JSON не роняет историю."""
    from infrastructure.database.models import DaySnapshot

    repo.session.add(DaySnapshot(date=datetime.date(2026, 10, 20),
                                 group="ДП-26", payload="{не json"))
    await repo.session.commit()
    assert await repo.snapshots.get(datetime.date(2026, 10, 20), "ДП-26") is None


def test_snapshot_helper_sets_group():
    """`group` обязателен: без него звонки берутся по fallback I_IV.

    У 2–3 курса вторая пара кончается в 12:20, а не в 12:40.
    """
    import inspect

    from tgbot.handlers import user as user_handler

    src = inspect.getsource(user_handler._snapshot_lessons)
    assert "item.group = group" in src


def test_snapshot_depth_is_fourteen():
    """Простой в четыре дня не должен закрывать дыру навсегда."""
    import inspect

    src = inspect.getsource(notify_edits.snapshot_past_days)
    assert "days_back: int = 14" in src


def test_snapshot_keeps_empty_days():
    import inspect

    src = inspect.getsource(notify_edits.snapshot_past_days)
    code = "\n".join(line.split("#", 1)[0] for line in src.splitlines())
    assert "if not slots:" not in code, "пустые дни снова пропускаются"


def test_history_merges_archive_dates():
    import inspect

    from tgbot.handlers import user as user_handler

    src = inspect.getsource(user_handler._hist_page)
    assert "get_dates_for_group" in src
    assert "snapshots.get_dates_for_group" in src
