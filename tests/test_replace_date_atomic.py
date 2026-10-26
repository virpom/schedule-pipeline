"""`replace_date` не должен оставлять день пустым при сбое вставки.

План 003. Раньше было два коммита: delete фиксировался отдельно, и
упавшая вставка оставляла день без пар. `materialize` зовёт метод 14 раз
подряд, так что падение на восьмом дне давало ровно один пустой день
посреди окна — студент видел «Занятий нет» за конкретное число.

Вставка реально падала на проде: наложение двух пар вуза нарушает
`uc_college_lesson` (UNIQUE по date, group, para).
"""
import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from infrastructure.database.models import Base, CollegeLesson
from infrastructure.database.repo.requests import RequestsRepo


async def make_env():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


DATE = datetime.date(2026, 10, 27)


def row(para: int) -> dict:
    return dict(date=DATE, group="ДП-26", para=para, para_end=para,
                subject="Математика", teacher="Иванов И.И.", room="101",
                source_url="http://x", source="site", changed=False, action="")


async def _count(session) -> int:
    return len(list(await session.execute(select(CollegeLesson))))


async def test_failed_insert_keeps_previous_day():
    """Главное: день не опустел.

    Дубликат (date, group, para) нарушает уникальный ключ — это самый
    вероятный сценарий падения на проде.
    """
    engine, pool = await make_env()
    try:
        async with pool() as session:
            repo = RequestsRepo(session)
            await repo.college_lessons.replace_date(DATE, [row(1), row(2)])
            assert await _count(session) == 2

            try:
                await repo.college_lessons.replace_date(DATE, [row(3), row(3)])
            except Exception:
                pass

            assert await _count(session) == 2, "день остался пустым — план 003"
    finally:
        await engine.dispose()


async def test_session_usable_after_failure():
    """После сбоя сессия должна быть рабочей.

    Без rollback она остаётся в состоянии «транзакция сломана», и
    следующая запись падает уже по другой причине.
    """
    engine, pool = await make_env()
    try:
        async with pool() as session:
            repo = RequestsRepo(session)
            await repo.college_lessons.replace_date(DATE, [row(1)])

            try:
                await repo.college_lessons.replace_date(DATE, [row(9), row(9)])
            except Exception:
                pass

            # Не бросает — сессия откачена.
            await repo.college_lessons.replace_date(DATE, [row(5)])
            assert await _count(session) == 1
    finally:
        await engine.dispose()


async def test_normal_replace_still_works():
    """Обычная замена переписывает день целиком."""
    engine, pool = await make_env()
    try:
        async with pool() as session:
            repo = RequestsRepo(session)
            await repo.college_lessons.replace_date(DATE, [row(1), row(2)])
            await repo.college_lessons.replace_date(DATE, [row(5)])

            rows = list(await session.execute(select(CollegeLesson)))
            assert len(rows) == 1
            assert rows[0][0].para == 5
    finally:
        await engine.dispose()


async def test_empty_list_clears_day():
    """Пустой список — законная очистка дня, не ошибка."""
    engine, pool = await make_env()
    try:
        async with pool() as session:
            repo = RequestsRepo(session)
            await repo.college_lessons.replace_date(DATE, [row(1)])
            await repo.college_lessons.replace_date(DATE, [])
            assert await _count(session) == 0
    finally:
        await engine.dispose()
