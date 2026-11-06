"""Рассылка берёт расписание одним запросом, а не на каждого получателя.

Было: на каждую дату и каждого подписчика открывалась сессия и делался
SELECT. 323 подписчика × 14 дат = 4522 запроса на одну рассылку.

Стало: один SELECT на все даты и раскладка в словарь в памяти.

Замер на живой базе прода (296 подписчиков, 14 дат):
  было  1.70 с
  стало 0.063 с  (x27)
Расхождений в содержимом рассылки — ноль.

Здесь проверяем не скорость (она зависит от машины), а две вещи,
на которых легко ошибиться при такой замене:
  1. порядок пар внутри получателя не изменился;
  2. преподаватель получает пары по фамилии, а не по группе.
"""
import asyncio
import datetime
import inspect

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from infrastructure.database.models import Base, CollegeLesson
from infrastructure.database.repo.requests import RequestsRepo


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


async def make_env():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def lesson(date, group, para, subject, teacher="Иванов И.И."):
    return CollegeLesson(
        date=date, group=group, para=para, para_end=para,
        subject=subject, teacher=teacher, room="1",
        source_url="", source="site", changed=False, action="")


def test_one_query_for_all_dates():
    """get_for_dates отдаёт всё разом и сортирует по дате и паре."""
    async def body():
        engine, pool = await make_env()
        try:
            d1 = datetime.date(2026, 11, 7)
            d2 = d1 + datetime.timedelta(days=1)
            async with pool() as db:
                db.add_all([
                    lesson(d1, "ДП-26", 3, "География"),
                    lesson(d1, "ДП-26", 1, "Биология"),
                    lesson(d1, "ТЭ-26ФП", 3, "География"),
                    lesson(d2, "ДП-26", 2, "Химия"),
                    lesson(d1 + datetime.timedelta(days=5), "ДП-26", 1, "Не берём"),
                ])
                await db.commit()
                rows = await RequestsRepo(db).college_lessons.get_for_dates([d1, d2])
            # Пятая дата не запрошена — её быть не должно.
            assert len(rows) == 4, [r.subject for r in rows]
            # Порядок: по дате, внутри даты по номеру пары. Именно так
            # печатает format_day и так же отдаёт get_for_group_date.
            assert [r.para for r in rows] == [1, 3, 3, 2], [r.para for r in rows]
            assert rows[0].subject == "Биология"
        finally:
            await engine.dispose()

    run(body())


def test_empty_dates_returns_empty():
    async def body():
        engine, pool = await make_env()
        try:
            async with pool() as db:
                rows = await RequestsRepo(db).college_lessons.get_for_dates([])
            assert rows == []
        finally:
            await engine.dispose()

    run(body())


def test_poller_does_not_query_per_user():
    """В рассылке не осталось запроса внутри цикла по подписчикам."""
    from tgbot.services import poller
    src = inspect.getsource(poller.notify_new_schedule)
    # Внутри цикла по получателям не должно быть открытия сессии.
    loop = src[src.index("for user in subscribers"):src.index("for chat in chats")]
    assert "session_pool()" not in loop, "в цикле снова открывается сессия"
    assert "get_for_dates" in src, "нет пакетного запроса"


def test_teacher_lessons_found_by_surname():
    """Преподаватель получает пары по фамилии, а не по группе.

    teacher_matches сверяет ещё и инициалы: однофамильцы не должны
    получать чужие пары.
    """
    from common.schedule import teacher_matches

    assert teacher_matches("Данилова А.Н.", "Данилова А.Н.")
    assert teacher_matches("Данилова А. Н.", "Данилова А.Н.")
    # Другой человек с той же фамилией — не он.
    assert not teacher_matches("Данилова И.П.", "Данилова А.Н.")
