"""Замены на сегодня не стираются, когда методист убрал их из файла.

Методист выкладывает листок замен на следующий день и убирает из него
прошедший. В файле 5 ноября утром лежали замены на 5-е, после обеда —
только на 6-е.

Прежний код удалял ВСЕ сайтовые замены и вставлял то, что пришло.
Сегодняшние исчезали, материализация собирала день заново по базовому
расписанию, и студент в разгар учебного дня получал «Расписание
изменилось» с пустыми заменами — то есть НЕВЕРНОЕ расписание на
сегодня. Прод, 05.11.2026, 11:04.

Раз замену показали и по ней пошли на пары, она верна до конца дня:
файл — не истина на прошедшие даты.
"""
import datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from infrastructure.database.models import Base, Substitution
from tgbot.services.sync_eios import replace_substitutions


class _Sub:
    """Минимальный ParsedSub: replace_substitutions читает только поля."""

    def __init__(self, date, group="ДП-26", para=1, subject="История",
                 action="replace", was=""):
        self.date = date
        self.group = group
        self.para = para
        self.subject = subject
        self.teacher = "Куранова Е.И."
        self.room = "406"
        self.action = action
        self.was = was


class _Repo:
    def __init__(self, session):
        self.session = session

    async def settings_get(self, key):
        return None


@pytest.fixture
async def session():
    from sqlalchemy.ext.asyncio import create_async_engine
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession,
                               expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


async def _rows(session):
    return (await session.execute(select(Substitution))).scalars().all()


@pytest.mark.asyncio
async def test_today_survives_when_file_drops_it(session):
    today = datetime.date.today()
    repo = _Repo(session)

    # Утром: замена на сегодня и на завтра.
    await replace_substitutions(repo, [
        _Sub(today, subject="Деловая культура"),
        _Sub(today + datetime.timedelta(days=1), subject="История"),
    ])
    assert len(await _rows(session)) == 2

    # После обеда: в файле только завтрашняя.
    await replace_substitutions(repo, [
        _Sub(today + datetime.timedelta(days=1), subject="История России"),
    ])

    rows = await _rows(session)
    dates = sorted(r.date for r in rows)
    assert today in dates, "сегодняшняя замена стёрта — день станет неверным"
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_today_not_duplicated_on_resend(session):
    today = datetime.date.today()
    repo = _Repo(session)
    await replace_substitutions(repo, [_Sub(today)])
    # Тот же файл пришёл снова — второй строки быть не должно (UNIQUE слот).
    await replace_substitutions(repo, [_Sub(today)])
    assert len(await _rows(session)) == 1


@pytest.mark.asyncio
async def test_future_still_replaced(session):
    """Будущие даты по-прежнему переписываются — это и есть замены."""
    tomorrow = datetime.date.today() + datetime.timedelta(days=1)
    repo = _Repo(session)
    await replace_substitutions(repo, [_Sub(tomorrow, subject="Было")])
    await replace_substitutions(repo, [_Sub(tomorrow, subject="Стало")])
    rows = await _rows(session)
    assert len(rows) == 1
    assert rows[0].subject == "Стало"
