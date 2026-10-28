"""Запасная сетка звонков покрывает шестую пару обычного дня.

План 167. `DEFAULT_BELL` (`bell_schedule.py`) описывал только пары 1..5
для «Остальных дней», хотя «стандартное.docx» отдаёт там **шесть**:
п6 18:05–18:50 / 18:55–19:40. Шестая пара реальна — в `college_lesson`
она есть у ДОУ-24, ПРф-24, ЭОф-24.

`seed_if_empty` засевает этой константой чистую базу, и до первой
успешной синхронизации `format_day` не находил звонок на 6-ю пару:
подставлялась заглушка «пара 6», а на экране звонков шестой пары
не было вовсе.

Понедельник не трогаем: в `bells-monday.docx` пары 1..5, константа
с текстом файла совпадает.
"""
import datetime

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from common.schedule import MAX_PARA, format_bell, format_day
from infrastructure.database.models import Base
from infrastructure.database.repo.requests import RequestsRepo


@pytest.fixture
async def repo():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    pool = async_sessionmaker(engine, expire_on_commit=False)
    async with pool() as session:
        yield RequestsRepo(session)
    await engine.dispose()


class Lesson:
    def __init__(self, para, group="ДОУ-24"):
        self.para = para
        self.para_end = para
        self.subject = "Архивное дело"
        self.teacher = "Тест Т.Т."
        self.room = "101"
        self.group = group
        self.time_note = ""
        self.action = ""
        self.changed = False
        self.comment = ""


@pytest.mark.asyncio
async def test_seed_has_sixth_para_for_other_days(repo):
    """После засева у обоих потоков есть звонок на все пары 1..MAX_PARA."""
    await repo.bell_schedule.seed_if_empty()
    bell, _ = await repo.bell_schedule.get_context()
    missing = [
        (cg, p)
        for cg in ("I_IV", "II_III")
        for p in range(1, MAX_PARA + 1)
        if ("OTHER", cg, p) not in bell
    ]
    assert not missing, f"в засеянной сетке нет слотов обычного дня: {missing}"


@pytest.mark.asyncio
async def test_sixth_para_has_time_on_clean_db(repo):
    """Главное: день с 6-й парой показывает время, а не «пара 6»."""
    await repo.bell_schedule.seed_if_empty()
    bell, lunches = await repo.bell_schedule.get_context()

    text = format_day(datetime.date(2026, 10, 28), [Lesson(6)], bell, lunches)

    assert "пара 6" not in text, f"заглушка вместо времени:\n{text}"
    assert "18:05–19:40" in text, text


@pytest.mark.asyncio
async def test_bell_screen_lists_sixth_para(repo):
    """Экран звонков тоже показывает шестую пару обычного дня."""
    await repo.bell_schedule.seed_if_empty()
    bell, lunches = await repo.bell_schedule.get_context()

    text = format_bell(bell, lunches)
    other = text.split("<b>Остальные дни</b>", 1)[1]
    assert other.count("6 пара") == 2, other       # I_IV и II_III
    assert other.count("18:05–18:50 / 18:55–19:40") == 2, other
