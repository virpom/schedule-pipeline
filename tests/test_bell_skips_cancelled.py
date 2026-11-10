"""Отменённая пара не даёт звонков.

Прод, 10.11.2026, ДП-26. В листке замен стояло «НЕТ ПАРЫ» на пары 1–3,
но `bell._tick` смотрел только на номер пары и звонки не фильтровал:
студент получал «🔔 2 пара · Систематизация…» и шёл в колледж на
занятие, которого нет.

Проверка поведенческая: собираем день с отменённой парой, гоняем `_tick`
на нужной минуте и смотрим, что ушло в Telegram. Текстовый греп по
исходнику не поймал бы, если фильтр поставят не в том месте.
"""
import datetime

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from common.schedule import SUB_CANCEL, SUB_REPLACE
from infrastructure.database.models import Base
from infrastructure.database.repo.requests import RequestsRepo
from tgbot.services import bell as bell_mod

DATE = datetime.date(2026, 11, 10)
GROUP = "ДП-26"


@pytest.fixture
async def pool():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def _setup(pool):
    async with pool() as db:
        repo = RequestsRepo(db)
        # Пользователь с включёнными звонками «начало/конец».
        await repo.users.get_or_create_user(
            user_id=1, full_name="Тест", language="ru")
        await repo.users.set_group(1, GROUP)
        await repo.users.set_course(1, 1)
        await repo.users.set_bell_mode(1, "start_end")
        await repo.users.set_subscribed(1, True)
        # Сетка звонков на вторник: пара 1 — 09:00–10:35, пара 2 — 10:45–12:40.
        for para, start, end in ((1, (9, 0), (10, 35)), (2, (10, 45), (12, 40))):
            await repo.bell_schedule.upsert(
                "OTHER", "I_IV", para,
                datetime.time(*start), datetime.time(*end))
        # Пара 1 отменена, пара 2 заменена (звонок должен быть).
        await repo.college_lessons.bulk_insert([
            dict(date=DATE, group=GROUP, para=1, para_end=1,
                 subject="Отменённый предмет", teacher="", room="",
                 action=SUB_CANCEL, source="manual"),
            dict(date=DATE, group=GROUP, para=2, para_end=2,
                 subject="Живой предмет", teacher="", room="",
                 action=SUB_REPLACE, source="manual"),
        ])
    return repo


@pytest.mark.asyncio
async def test_cancelled_para_sends_no_bell(pool, monkeypatch):
    """На минуту начала отменённой пары ничего не уходит."""
    await _setup(pool)

    sent: list[str] = []

    async def fake_send(bot, chat_id, text):
        sent.append(text)
        return True

    monkeypatch.setattr(bell_mod, "send_message", fake_send)

    now = datetime.datetime.combine(DATE, datetime.time(9, 0))
    await bell_mod._tick(bot=None, session_pool=pool, now=now)

    assert sent == [], f"пришли звонки на отменённую пару: {sent}"


@pytest.mark.asyncio
async def test_replaced_para_still_sends_bell(pool, monkeypatch):
    """Замена звонок даёт — иначе фильтр съел бы живые пары."""
    await _setup(pool)

    sent: list[str] = []

    async def fake_send(bot, chat_id, text):
        sent.append(text)
        return True

    monkeypatch.setattr(bell_mod, "send_message", fake_send)

    now = datetime.datetime.combine(DATE, datetime.time(10, 45))
    await bell_mod._tick(bot=None, session_pool=pool, now=now)

    assert sent, "звонок на заменённую пару не пришёл"
    assert "Живой предмет" in sent[0], sent
