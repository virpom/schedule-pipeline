"""Откат правки редактора: журнал должен двигаться, «add» — убирать пару."""
import asyncio
import json

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from infrastructure.database.models import Base, ScheduleEdit
from infrastructure.database.repo.requests import RequestsRepo


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


async def make_env():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def test_undo_removes_added_lesson():
    """Откат добавленной пары убирает её из расписания.

    Раньше пробовали вернуть old_value, а у добавления он пустой —
    пара оставалась на месте, и «Откатить» не работало.
    """
    async def scenario():
        engine, pool = await make_env()
        try:
            async with pool() as db:
                repo = RequestsRepo(db)
                await repo.base_lessons.upsert("ДП-26", "ANY", 1, 1,
                                               "Тестовый предмет", source="manual")
                db.add(ScheduleEdit(
                    user_id=1, group="ДП-26", para=1, layer="base",
                    action="add", old_value="",
                    new_value=json.dumps(dict(weekday=1, parity="ANY", para=1,
                                              subject="Тестовый предмет"))))
                await db.commit()

                last = await repo.edit_log.get_last("ДП-26")
                assert last is not None and last.action == "add"

                # Откат: удаляем пару (то, что теперь делает cb_undo).
                await repo.base_lessons.delete_slot("ДП-26", "ANY", 1, 1)
                left = await repo.base_lessons.get_day("ДП-26", 1, "ANY")
                assert left == []
        finally:
            await engine.dispose()
    run(scenario())


def test_undo_advances_journal():
    """После отката запись уходит из журнала — иначе откат повторяется."""
    async def scenario():
        engine, pool = await make_env()
        try:
            async with pool() as db:
                repo = RequestsRepo(db)
                db.add(ScheduleEdit(user_id=1, group="ДП-26", para=1,
                                    layer="base", action="edit",
                                    old_value=json.dumps(dict(subject="Старое")),
                                    new_value=json.dumps(dict(weekday=1, parity="ANY",
                                                              subject="Новое"))))
                await db.commit()

                first = await repo.edit_log.get_last("ДП-26")
                assert first is not None

                await repo.edit_log.delete(first.id)
                assert await repo.edit_log.get_last("ДП-26") is None, \
                    "журнал не сдвинулся — откат повторит ту же правку"
        finally:
            await engine.dispose()
    run(scenario())
