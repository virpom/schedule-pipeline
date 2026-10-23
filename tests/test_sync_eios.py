"""Тесты маппинга и загрузки слоёв расписания.

Работаем на временной SQLite, без сети.
"""
import asyncio
import datetime

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from common.schedule import PARITY_ANY, PARITY_EVEN, PARITY_ODD
from infrastructure.database.models import Base
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


def test_manual_edit_on_same_slot_as_site_does_not_crash(tmp_path):
    """Ручная правка на том же слоте, что и пара из файла, не роняет загрузку.

    Регрессия: обе строки вставлялись на одно (group, parity, weekday, para),
    и UNIQUE падал с IntegrityError. Ручная правка должна побеждать.
    """
    async def body(repo):
        await repo.base_lessons.upsert("ДП-26", PARITY_ANY, 1, 1, "РУЧНАЯ",
                                       "Староста С.С.", source="manual")
        # В файле на этот же слот есть пара.
        lessons = [ParsedLesson("ДП-26", 1, 1, 1, "С сайта")]

        for _ in range(2):  # повторная загрузка тоже не должна падать
            await sync_eios.replace_base_lessons(repo, lessons)
            day = await repo.base_lessons.get_day("ДП-26", 1, PARITY_ANY)
            assert [l.subject for l in day] == ["РУЧНАЯ"]
            assert [l.source for l in day] == ["manual"]

    _run(_with_repo(tmp_path, body))


def test_replace_base_lessons_idempotent_count(tmp_path):
    """Повторная загрузка не размножает строки."""
    async def body(repo):
        lessons = [
            ParsedLesson("ДП-26", 1, 1, 1, "Математика"),
            ParsedLesson("ДП-26", 1, 1, 2, "Физика"),
        ]
        for _ in range(3):
            await sync_eios.replace_base_lessons(repo, lessons)
            assert await repo.base_lessons.count() == 2

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


# --- окно дат должно сдвигаться ---------------------------------------------

def test_materialize_writes_all_days(tmp_path):
    """Материализация должна заполнять всё окно, а не только «сегодня».

    Если её вызывать только при изменении файлов, окно не сдвигается вперёд
    и через две недели расписание «кончается».
    """
    async def body(repo):
        await sync_eios.replace_base_lessons(repo, [
            ParsedLesson("ДП-26", 1, 1, 1, "Математика", "Иванов И.И."),
        ])
        days = await sync_eios.materialize(repo, days=14)
        assert days == 14

        import datetime as dt
        today = dt.date.today()
        for offset in (0, 7, 13):
            date = today + dt.timedelta(days=offset)
            rows = await repo.college_lessons.get_for_group_date("ДП-26", date)
            # Понедельник есть только раз в неделю, поэтому проверяем
            # не наличие пар, а что дата вообще обработана.
            assert date.isoweekday() != 1 or rows

        # Дальше окна данных быть не должно.
        far = today + dt.timedelta(days=20)
        assert await repo.college_lessons.get_for_group_date("ДП-26", far) == []

    _run(_with_repo(tmp_path, body))


def test_materialize_applies_substitutions(tmp_path):
    """В материализованные дни попадают замены, а не только база."""
    async def body(repo):
        import datetime as dt
        today = dt.date.today()
        # Берём ближайший понедельник в пределах окна.
        offset = (7 - today.weekday()) % 7
        date = today + dt.timedelta(days=offset)

        await sync_eios.replace_base_lessons(repo, [
            ParsedLesson("ДП-26", 1, 1, 1, "Математика", "Иванов И.И."),
            ParsedLesson("ДП-26", 1, 1, 2, "Физика", "Петров П.П."),
        ])
        await sync_eios.replace_substitutions(repo, [
            ParsedSub(date, "ДП-26", 2, "replace", "История", "Новый Н.Н.", "ауд. 9"),
        ])
        await sync_eios.materialize(repo, days=14)

        rows = await repo.college_lessons.get_for_group_date("ДП-26", date)
        by_para = {r.para: r for r in rows}
        assert by_para[1].subject == "Математика"
        assert by_para[2].subject == "История"
        assert by_para[2].room == "ауд. 9"

    _run(_with_repo(tmp_path, body))


def test_materialize_keeps_manual_edits(tmp_path):
    """Ручная правка старосты переживает повторную материализацию.

    Раньше она отбрасывалась, если на том же слоте была пара из базы.
    """
    async def body(repo):
        import datetime as dt
        today = dt.date.today()
        offset = (7 - today.weekday()) % 7
        date = today + dt.timedelta(days=offset)

        await sync_eios.replace_base_lessons(repo, [
            ParsedLesson("ДП-26", 1, 1, 1, "Математика", "Иванов И.И."),
        ])
        await repo.college_lessons.bulk_insert([{
            "date": date, "group": "ДП-26", "para": 1, "para_end": 1,
            "subject": "РУЧНАЯ", "teacher": "Староста С.С.", "room": "",
            "source_url": "", "source": "manual",
        }])

        # Дважды: правка не должна «съедаться» ни первым, ни вторым прогоном.
        for _ in range(2):
            await sync_eios.materialize(repo, days=14)
            rows = await repo.college_lessons.get_for_group_date("ДП-26", date)
            manual = [r for r in rows if r.source == "manual"]
            assert len(manual) == 1
            assert manual[0].subject == "РУЧНАЯ"
            # На слоте 1 не должно быть двух пар.
            assert [r.para for r in rows].count(1) == 1

    _run(_with_repo(tmp_path, body))


# --- уведомления про замены --------------------------------------------------

def test_substitution_dates_include_weekend_and_monday(tmp_path):
    """Листок замен выдаётся сразу на несколько дней (СБ + ПН).

    Раньше рассылка брала фиксированное окно «сегодня + 2 дня» и теряла
    понедельник, если замены приходили в пятницу.
    """
    async def body(repo):
        import datetime as dt
        today = dt.date.today()
        sat = today + dt.timedelta(days=1)
        mon = today + dt.timedelta(days=3)
        await sync_eios.replace_substitutions(repo, [
            ParsedSub(sat, "ДП-26", 1, "replace", "A"),
            ParsedSub(mon, "ДП-26", 1, "replace", "B"),
        ])
        dates = await repo.substitutions.get_dates(today)
        assert sat in dates
        assert mon in dates, "понедельник должен попасть в уведомление"
        assert dates == sorted(dates)

    _run(_with_repo(tmp_path, body))


def test_substitution_dates_skip_past(tmp_path):
    """Прошедшие даты не попадают в рассылку."""
    async def body(repo):
        import datetime as dt
        today = dt.date.today()
        past = today - dt.timedelta(days=5)
        future = today + dt.timedelta(days=2)
        await sync_eios.replace_substitutions(repo, [
            ParsedSub(past, "ДП-26", 1, "replace", "A"),
            ParsedSub(future, "ДП-26", 1, "replace", "B"),
        ])
        dates = await repo.substitutions.get_dates(today)
        assert past not in dates
        assert future in dates

    _run(_with_repo(tmp_path, body))


def test_manual_substitution_on_same_slot_does_not_crash(tmp_path):
    """Ручная замена на том же слоте, что и замена с сайта, не роняет загрузку.

    Регрессия: UNIQUE по (date, group, para) падал, потому что обе строки
    вставлялись. Ручная правка должна побеждать.
    """
    async def body(repo):
        import datetime as dt
        d = dt.date(2026, 10, 26)
        await repo.substitutions.set(d, "ДП-26", 2, "replace", "РУЧНАЯ",
                                     "Староста С.С.", source="manual")
        subs = [
            ParsedSub(d, "ДП-26", 2, "replace", "С САЙТА", "Т.Т."),
            ParsedSub(d, "ДП-26", 3, "cancel"),
        ]
        for _ in range(2):
            await sync_eios.replace_substitutions(repo, subs)
            got = await repo.substitutions.get_for_date("ДП-26", d)
            assert len(got) == 2
            assert got[0].para == 2 and got[0].source == "manual"
            assert got[0].subject == "РУЧНАЯ"
            assert got[1].para == 3 and got[1].source == "site"

    _run(_with_repo(tmp_path, body))


def test_materialize_marks_days_published(tmp_path):
    """Материализация помечает дни опубликованными.

    Регрессия: таблицу schedule_file заполнял старый парсер, после перехода
    на ЭИОС её перестали обновлять. Из-за этого на пустой день студент видел
    «расписание ещё не выложено» вместо «занятий нет».
    """
    async def body(repo):
        import datetime as dt
        await repo.base_lessons.upsert("ДП-26", PARITY_ANY, 1, 1, "Математика",
                                       "Иванов И.И.", source="site")
        await sync_eios.materialize(repo, days=3)

        today = dt.date.today()
        for offset in range(3):
            date = today + dt.timedelta(days=offset)
            assert await repo.schedule_files.get_hash(date) is not None, \
                f"{date} должен считаться опубликованным"

    _run(_with_repo(tmp_path, body))
