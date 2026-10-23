"""Тесты маппинга и загрузки слоёв расписания.

Работаем на временной SQLite, без сети.
"""
import asyncio
import datetime

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from common.schedule import PARITY_ANY, PARITY_EVEN, PARITY_ODD
from infrastructure.database.models import Base, BaseLesson, Substitution
from infrastructure.database.repo.requests import RequestsRepo
from parsers.eios import PARITY_BOTH, PARITY_EVEN as PARSER_EVEN, PARITY_ODD as PARSER_ODD
from tgbot.services import sync_eios


@pytest.fixture()
def repo_factory(tmp_path):
    """Фабрика репозиториев на чистой БД."""
    engines = []

    def make():
        path = tmp_path / f"t{len(engines)}.db"
        engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
        engines.append(engine)
        return engine

    return make


def _run(coro):
    return asyncio.run(coro)


async def _with_repo(tmp_path, body):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/db.sqlite")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            return await body(RequestsRepo(session))
    finally:
        await engine.dispose()


# --- маппинг чётности --------------------------------------------------------

def test_db_parity_mapping():
    assert sync_eios.db_parity(PARITY_BOTH) == PARITY_ANY
    assert sync_eios.db_parity(PARSER_EVEN) == PARITY_EVEN
    assert sync_eios.db_parity(PARSER_ODD) == PARITY_ODD


def test_parity_offset_is_one():
    """Колледж считает чётность на единицу иначе, чем ISO.

    26.10.2026 — ISO-неделя 44 (чётная), у колледжа нечётная.
    """
    from common.schedule import week_parity

    d = datetime.date(2026, 10, 26)
    assert week_parity(d, 0) == PARITY_EVEN
    assert week_parity(d, sync_eios.PARITY_OFFSET) == PARITY_ODD


# --- загрузка базового расписания -------------------------------------------

class ParsedLesson:
    def __init__(self, group, course, day, para, subject, teacher="", parity=PARITY_BOTH):
        self.group = group
        self.course = course
        self.day = day
        self.para = para
        self.subject = subject
        self.teacher = teacher
        self.parity = parity
        self.time_note = None


def test_replace_base_lessons_stores_parity(tmp_path):
    async def body(repo):
        lessons = [
            ParsedLesson("ДП-26", 1, 1, 1, "Математика", "Иванов И.И.", PARITY_BOTH),
            ParsedLesson("ДП-26", 1, 1, 2, "Физика", "Петров П.П.", PARSER_ODD),
            ParsedLesson("ДП-26", 1, 1, 3, "Химия", "Сидоров С.С.", PARSER_EVEN),
        ]
        added = await sync_eios.replace_base_lessons(repo, lessons)
        assert added == 3

        both = await repo.base_lessons.get_day("ДП-26", 1, PARITY_ODD)
        # В нечётную неделю видны ANY + ODD, но не EVEN.
        assert [l.para for l in both] == [1, 2]

        even = await repo.base_lessons.get_day("ДП-26", 1, PARITY_EVEN)
        assert [l.para for l in even] == [1, 3]

    _run(_with_repo(tmp_path, body))


def test_replace_base_lessons_is_full_replace(tmp_path):
    """Повторная загрузка убирает пары, которых больше нет в файле."""
    async def body(repo):
        first = [ParsedLesson("ДП-26", 1, 1, p, f"Предмет {p}") for p in (1, 2, 3)]
        await sync_eios.replace_base_lessons(repo, first)
        assert await repo.base_lessons.count() == 3

        second = [ParsedLesson("ДП-26", 1, 1, 1, "Только первая")]
        await sync_eios.replace_base_lessons(repo, second)
        assert await repo.base_lessons.count() == 1

    _run(_with_repo(tmp_path, body))


def test_replace_base_lessons_keeps_manual(tmp_path):
    """Ручные правки старосты не затираются загрузкой с сайта."""
    async def body(repo):
        await repo.base_lessons.upsert("ДП-26", PARITY_ANY, 2, 1, "Ручная пара",
                                       "Ручной Р.Р.", source="manual")
        lessons = [ParsedLesson("ДП-26", 1, 1, 1, "С сайта")]
        await sync_eios.replace_base_lessons(repo, lessons)

        week = await repo.base_lessons.get_day("ДП-26", 2, PARITY_ODD)
        assert [l.subject for l in week] == ["Ручная пара"]
        day1 = await repo.base_lessons.get_day("ДП-26", 1, PARITY_ODD)
        assert [l.subject for l in day1] == ["С сайта"]

    _run(_with_repo(tmp_path, body))


# --- замены ------------------------------------------------------------------

class ParsedSub:
    def __init__(self, date, group, para, action, subject="", teacher="", room="", raw_now=""):
        self.date = date
        self.group = group
        self.para = para
        self.action = action
        self.subject = subject
        self.teacher = teacher
        self.room = room
        self.raw_now = raw_now


def test_replace_substitutions(tmp_path):
    async def body(repo):
        d = datetime.date(2026, 10, 26)
        subs = [
            ParsedSub(d, "ДП-26", 1, "replace", "История", "Иванов И.И.", "ауд. 5"),
            ParsedSub(d, "ДП-26", 2, "cancel"),
        ]
        assert await sync_eios.replace_substitutions(repo, subs) == 2

        got = await repo.substitutions.get_for_date("ДП-26", d)
        assert [(s.para, s.action) for s in got] == [(1, "replace"), (2, "cancel")]
        assert got[0].room == "ауд. 5"
        assert all(s.source == "site" for s in got)

    _run(_with_repo(tmp_path, body))


def test_replace_substitutions_is_full_replace(tmp_path):
    async def body(repo):
        d = datetime.date(2026, 10, 26)
        await sync_eios.replace_substitutions(
            repo, [ParsedSub(d, "ДП-26", 1, "replace", "A"),
                   ParsedSub(d, "ДП-26", 2, "replace", "B")])
        await sync_eios.replace_substitutions(
            repo, [ParsedSub(d, "ДП-26", 1, "replace", "C")])
        got = await repo.substitutions.get_for_date("ДП-26", d)
        assert [s.subject for s in got] == ["C"]

    _run(_with_repo(tmp_path, body))


# --- сопоставление групп -----------------------------------------------------

def test_resolve_groups_renames_and_skips():
    subs = [
        ParsedSub(datetime.date(2026, 10, 26), "ЭОК-26", 1, "replace", "A"),
        ParsedSub(datetime.date(2026, 10, 26), "ДОУ - 25", 1, "replace", "B"),
        ParsedSub(datetime.date(2026, 10, 26), "ЭОф-26", 1, "replace", "C"),
        ParsedSub(datetime.date(2026, 10, 26), "НЕТ-ТАКОЙ-99", 1, "replace", "D"),
    ]
    known = ["ЭОк-26", "ДОУ-25", "ЭО-26ФП"]
    got = sync_eios._resolve_groups(subs, known)
    assert [s.group for s in got] == ["ЭОк-26", "ДОУ-25", "ЭО-26ФП"]


# --- сквозная сборка дня -----------------------------------------------------

def test_base_plus_substitution_end_to_end(tmp_path):
    """База + замена → то, что увидит студент."""
    async def body(repo):
        from tgbot.services.schedule_layer import get_day_slots

        d = datetime.date(2026, 10, 26)  # нечётная неделя у колледжа
        await sync_eios.replace_base_lessons(repo, [
            ParsedLesson("ДП-26", 1, 1, 1, "Математика", "Иванов И.И."),
            ParsedLesson("ДП-26", 1, 1, 2, "Физика", "Петров П.П."),
            ParsedLesson("ДП-26", 1, 1, 3, "Химия", "Сидоров С.С."),
        ])
        await sync_eios.replace_substitutions(repo, [
            ParsedSub(d, "ДП-26", 2, "replace", "История", "Новый Н.Н.", "ауд. 7"),
            ParsedSub(d, "ДП-26", 3, "cancel"),
        ])

        slots = await get_day_slots(repo, "ДП-26", d, sync_eios.PARITY_OFFSET)
        assert [(s.para, s.subject) for s in slots] == [
            (1, "Математика"),
            (2, "История"),
        ]
        assert slots[1].changed is True
        assert slots[1].room == "ауд. 7"

    _run(_with_repo(tmp_path, body))
