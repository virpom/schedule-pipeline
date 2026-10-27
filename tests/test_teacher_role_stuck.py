"""Роль `teacher` не пишется до выбора фамилии.

План 046. `cb_role_teacher` сразу писал `role='teacher'` в базу, до
выбора подразделения и фамилии. Если человек уходил на этом шаге,
оставалось `role='teacher'` с `teacher_name=NULL` — состояние
непоправимое из UI: `/start` снова показывал выбор роли, а выбрать
фамилию было негде. Рассылки такому человеку приходили как «занятий
нет».

Проверка на проде 27.10: застрявших с `role='teacher'` и пустой
фамилией нет — mourvane уже выбрал «Данилова А.Н.». Но состояние
достижимо в любую минуту, поэтому правка не косметическая.

Второй дефект плана — `AttributeError` при `teacher_name=None` в
`get_dates_for_teacher` и `get_all_for_teacher` — воспроизведён и
закрыт.
"""
import inspect

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from infrastructure.database.models import Base
from infrastructure.database.repo.requests import RequestsRepo
from tgbot.handlers import user as user_handler


@pytest.fixture
async def repo():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    pool = async_sessionmaker(engine, expire_on_commit=False)
    async with pool() as session:
        yield RequestsRepo(session)
    await engine.dispose()


def test_role_not_written_before_teacher_pick():
    """`cb_role_teacher` не трогает базу."""
    src = inspect.getsource(user_handler.cb_role_teacher)
    assert "set_role" not in src, "роль снова пишется до выбора фамилии"


def test_role_written_with_name():
    """Роль ставится там, где фамилия уже известна."""
    src = inspect.getsource(user_handler.cb_teacher)
    assert 'set_role(user.id, "teacher")' in src
    assert "set_teacher_name" in src


@pytest.mark.asyncio
async def test_dates_for_teacher_handles_none(repo):
    """None не роняет метод — раньше был AttributeError."""
    assert await repo.college_lessons.get_dates_for_teacher(None) == []


@pytest.mark.asyncio
async def test_dates_for_teacher_handles_empty(repo):
    """Пустая строка не выгружает всю таблицу."""
    assert await repo.college_lessons.get_dates_for_teacher("") == []
    assert await repo.college_lessons.get_dates_for_teacher("   ") == []


@pytest.mark.asyncio
async def test_all_for_teacher_handles_none(repo):
    assert await repo.college_lessons.get_all_for_teacher(None) == []


@pytest.mark.asyncio
async def test_all_for_teacher_handles_empty(repo):
    assert await repo.college_lessons.get_all_for_teacher("") == []


@pytest.mark.asyncio
async def test_teacher_with_name_still_works(repo):
    """Защита не сломала нормальный путь."""
    await repo.college_lessons.replace_date(
        __import__("datetime").date(2026, 11, 3),
        [{"date": __import__("datetime").date(2026, 11, 3),
          "group": "ДП-26", "para": 1, "para_end": 1,
          "subject": "Математика", "teacher": "Силин Д.С.",
          "room": "410", "source_url": "", "source": "site",
          "changed": False, "action": "", "time_note": ""}])
    dates = await repo.college_lessons.get_dates_for_teacher("Силин Д.С.")
    assert dates, "нормальный поиск перестал работать"
