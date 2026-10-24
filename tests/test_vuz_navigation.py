"""Навигация по группам: вуз/колледж → факультет → форма → курс → группа."""
import asyncio

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from infrastructure.database.models import Base, VuzGroup
from infrastructure.database.repo.requests import RequestsRepo
from parsers import vuz
from tgbot.services import sync_vuz


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


async def make_env():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


GROUPS = [
    vuz.VuzGroup("ЭК-26@vuz", "FEU", 1, "full"),
    vuz.VuzGroup("ЭК-25@vuz", "FEU", 2, "full"),
    vuz.VuzGroup("ЭК-25оз@vuz", "FEU", 2, "part"),
    vuz.VuzGroup("ГД-26@vuz", "GTF", 1, "full"),
]


async def seed(pool):
    """Разложить группы по формам, как это делает синхронизация."""
    async with pool() as db:
        repo = RequestsRepo(db)
        for form in ("full", "part"):
            own = [g for g in GROUPS if g.form == form]
            if own:
                await sync_vuz.replace_vuz_groups(repo, own, form)
        return repo


# --- справочник --------------------------------------------------------------

def test_repo_lists_all_groups():
    async def scenario():
        engine, pool = await make_env()
        try:
            await seed(pool)
            async with pool() as db:
                rows = await RequestsRepo(db).vuz_groups.all()
                assert len(rows) == len(GROUPS)
        finally:
            await engine.dispose()
    run(scenario())


def test_courses_filtered_by_faculty_and_form():
    """Курсы разные у факультетов и форм — это и есть смысл трёх уровней."""
    async def scenario():
        engine, pool = await make_env()
        try:
            await seed(pool)
            async with pool() as db:
                repo = RequestsRepo(db)
                assert await repo.vuz_groups.courses("FEU", "full") == [1, 2]
                assert await repo.vuz_groups.courses("FEU", "part") == [2]
                assert await repo.vuz_groups.courses("GTF", "full") == [1]
        finally:
            await engine.dispose()
    run(scenario())


def test_groups_filtered_by_course():
    async def scenario():
        engine, pool = await make_env()
        try:
            await seed(pool)
            async with pool() as db:
                repo = RequestsRepo(db)
                assert await repo.vuz_groups.by_course("FEU", "full", 2) == ["ЭК-25@vuz"]
                assert await repo.vuz_groups.by_course("FEU", "full", 1) == ["ЭК-26@vuz"]
        finally:
            await engine.dispose()
    run(scenario())


def test_unknown_combination_gives_empty_list():
    """Пустой список, а не падение: справочник мог ещё не загрузиться."""
    async def scenario():
        engine, pool = await make_env()
        try:
            await seed(pool)
            async with pool() as db:
                repo = RequestsRepo(db)
                assert await repo.vuz_groups.by_course("FEU", "full", 6) == []
                assert await repo.vuz_groups.courses("XXX", "full") == []
        finally:
            await engine.dispose()
    run(scenario())


def test_get_group_returns_faculty_and_course():
    """Курс берём из справочника — студент не должен выбирать его сам."""
    async def scenario():
        engine, pool = await make_env()
        try:
            await seed(pool)
            async with pool() as db:
                info = await RequestsRepo(db).vuz_groups.get("ЭК-25оз@vuz")
                assert info is not None
                assert info.faculty == "FEU"
                assert info.course == 2
                assert info.form == "part"
        finally:
            await engine.dispose()
    run(scenario())


def test_get_unknown_group_is_none():
    async def scenario():
        engine, pool = await make_env()
        try:
            await seed(pool)
            async with pool() as db:
                assert await RequestsRepo(db).vuz_groups.get("НЕТ-99@vuz") is None
        finally:
            await engine.dispose()
    run(scenario())


# --- звонки ------------------------------------------------------------------

def test_vuz_student_gets_vuz_bells():
    """У вуза 8 пар до 22:00. Раньше студент получал звонки колледжа."""
    from common.schedule import VUZ_GROUP, bells_group

    assert bells_group("ЭК-23@vuz", 2) == VUZ_GROUP
    assert bells_group("ЭК-23@vuz", None) == VUZ_GROUP


def test_college_student_keeps_course_bells():
    from common.schedule import bells_group

    assert bells_group("ТЭ-26ФП", 1) == "I_IV"
    assert bells_group("ТЭ-25ФП", 2) == "II_III"


def test_bells_group_falls_back_to_course():
    """Без группы (старые записи) остаётся прежнее поведение по курсу."""
    from common.schedule import bells_group

    assert bells_group(None, 1) == "I_IV"
    assert bells_group(None, 3) == "II_III"
    assert bells_group(None, None) is None


# --- отображение -------------------------------------------------------------

def test_strip_unit_hides_suffix():
    from common.schedule import strip_unit

    assert strip_unit("ЭК-23@vuz") == "ЭК-23"
    assert strip_unit("ТЭ-26ФП") == "ТЭ-26ФП"
    assert strip_unit(None) is None
