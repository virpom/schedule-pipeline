"""Навигация по группам: вуз/колледж → факультет → форма → курс → группа."""
import asyncio

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from infrastructure.database.models import Base
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


# --- отображение дня ---------------------------------------------------------

def _lesson(group="ЭК-26-2@vuz", para=6):
    class L:
        pass
    l = L()
    l.group, l.para, l.para_end = group, para, para
    l.subject, l.teacher, l.room, l.changed = "Физика", "Иванов И.И.", "", False
    return l


def _bells():
    import datetime as dt
    return {("MONDAY", "ALL", 0): type("B", (), {"start": dt.time(9, 0),
                                                 "end": dt.time(9, 20)})(),
            ("OTHER", "VUZ", 6): type("B", (), {"start": dt.time(17, 10),
                                                "end": dt.time(18, 40)})()}


def test_rov_not_shown_for_vuz():
    """«Разговоры о важном» — линейка колледжа, у вуза её нет.

    Звонок лежит в bell_schedule с course_group='ALL', поэтому без
    проверки подразделения он попадал в расписание студента вуза.
    """
    import datetime as dt
    from common.schedule import format_day

    text = format_day(dt.date(2026, 10, 26), [_lesson()], _bells(), {},
                      show_rov=True)
    assert "Разговоры о важном" not in text


def test_rov_still_shown_for_college():
    """У колледжа линейка остаётся — фикс не должен её убрать."""
    import datetime as dt
    from common.schedule import format_day

    text = format_day(dt.date(2026, 10, 26), [_lesson(group="ТЭ-26ФП")],
                      _bells(), {}, show_rov=True)
    assert "Разговоры о важном" in text


def test_vuz_has_own_source_state():
    """Сайт колледжа и сайт вуза — разные источники, флаги независимы."""
    import asyncio
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from infrastructure.database.models import Base
    from infrastructure.database.repo.requests import RequestsRepo
    from tgbot.services import source_state

    async def scenario():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        pool = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with pool() as db:
                repo = RequestsRepo(db)
                # Вуз синхронизировался, колледж — нет.
                await source_state.mark_ok_vuz(repo)
                assert await source_state.is_stale_vuz(repo) is False
                assert await source_state.is_stale(repo) is True
                # И наоборот.
                await source_state.mark_ok(repo)
                assert await source_state.is_stale(repo) is False
        finally:
            await engine.dispose()

    asyncio.get_event_loop_policy().new_event_loop().run_until_complete(scenario())


def test_substitution_mark_next_to_lesson():
    """🔄 стоит в строке самой пары — видно, что она не по постоянному плану."""
    import datetime as dt
    from common.schedule import SUB_MARK, format_day

    l = _lesson()
    l.changed = True
    text = format_day(dt.date(2026, 10, 26), [l], _bells(), {})
    line = next(x for x in text.splitlines() if "Физика" in x)
    assert SUB_MARK in line, f"нет значка в строке пары: {line!r}"
    # Именно рядом с предметом, а не отдельной строкой.
    assert line.index(SUB_MARK) > line.index("Физика")


def test_unchanged_lesson_has_no_mark():
    """Обычная пара без значка — иначе значок перестанет что-то значить."""
    import datetime as dt
    from common.schedule import SUB_MARK, format_day

    text = format_day(dt.date(2026, 10, 26), [_lesson()], _bells(), {})
    assert SUB_MARK not in text


def test_vuz_substitution_mark_shown():
    """Тот же значок для вуза: путь отображения общий."""
    import datetime as dt
    from common.schedule import SUB_MARK, format_day

    l = _lesson(group="ЭК-26-2@vuz", para=7)
    l.changed = True
    text = format_day(dt.date(2026, 10, 26), [l], _bells(), {}, show_rov=False)
    assert SUB_MARK in text


def test_college_picker_excludes_vuz_groups():
    """В списке «Колледж» не должно быть групп вуза.

    college_lesson общая для обоих подразделений, поэтому
    get_groups() отдаёт и группы с суффиксом @vuz. Без фильтра
    студент колледжа видел 92 чужие группы и мог открыть расписание
    вуза, приняв его за своё.
    """
    import asyncio
    import datetime as dt
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from infrastructure.database.models import Base, CollegeLesson
    from infrastructure.database.repo.requests import RequestsRepo
    from tgbot.handlers import user as uh

    async def scenario():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        pool = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with pool() as db:
                db.add_all([
                    CollegeLesson(date=dt.date(2026, 10, 26), group="ТЭ-26ФП",
                                  para=1, para_end=1, subject="Физика",
                                  teacher="", room="", source_url="",
                                  source="site", changed=False),
                    CollegeLesson(date=dt.date(2026, 10, 26), group="ЭК-26-2@vuz",
                                  para=1, para_end=1, subject="Матан",
                                  teacher="", room="", source_url="",
                                  source="site", changed=False),
                ])
                await db.commit()
                repo = RequestsRepo(db)
                kb = await uh._college_pick_kb(repo)
                names = [b.text for row in kb.inline_keyboard for b in row]
                assert "ТЭ-26ФП" in names
                assert not any("@vuz" in n for n in names), names
                assert "ЭК-26-2@vuz" not in names
        finally:
            await engine.dispose()

    asyncio.get_event_loop_policy().new_event_loop().run_until_complete(scenario())


# --- поиск преподавателя -----------------------------------------------------

def test_teacher_search_by_surname():
    """Человек ищет фамилию, а в расписании она с инициалами.

    Раньше teacher_matches обрабатывал только обратный случай
    (в паре одна фамилия, выбрано полное имя), поэтому поиск
    «Коленова» не находил ничего ни у вуза, ни у колледжа.
    """
    from common.schedule import teacher_matches

    assert teacher_matches("Коленова В.А.", "Коленова")
    assert teacher_matches("Коленова В. А.", "Коленова")   # пробел после точки
    assert teacher_matches("Коленова В.А.", "Коленова В.А.")
    assert teacher_matches("Ляшко", "Ляшко Д.В.")          # обратный случай


def test_teacher_search_does_not_match_others():
    """Совпадение по фамилии не должно склеивать разных людей."""
    from common.schedule import teacher_matches

    assert not teacher_matches("Коленова В.А.", "Кабышева")
    assert not teacher_matches("Коленова В.А.", "")
    assert not teacher_matches("", "Коленова")


def test_teacher_search_finds_vuz_lessons():
    """Пары вуза ищутся тем же запросом, что и колледжа."""
    import asyncio
    import datetime as dt
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from infrastructure.database.models import Base, CollegeLesson
    from infrastructure.database.repo.requests import RequestsRepo

    async def scenario():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        pool = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with pool() as db:
                db.add_all([
                    CollegeLesson(date=dt.date(2026, 10, 26), group="ЭК-26-1@vuz",
                                  para=3, para_end=3, subject="Презентации",
                                  teacher="Коленова В.А.", room="",
                                  source_url="", source="site", changed=False),
                    CollegeLesson(date=dt.date(2026, 10, 26), group="ТЭ-26ФП",
                                  para=1, para_end=1, subject="Физика",
                                  teacher="Ивасишина Е.Е.", room="",
                                  source_url="", source="site", changed=False),
                ])
                await db.commit()
                repo = RequestsRepo(db)
                found = await repo.college_lessons.get_all_for_teacher("Коленова")
                assert len(found) == 1
                assert found[0].group == "ЭК-26-1@vuz"
        finally:
            await engine.dispose()

    asyncio.get_event_loop_policy().new_event_loop().run_until_complete(scenario())


# --- чётность недель вуза ----------------------------------------------------

def test_vuz_parity_after_january_diverges_from_iso():
    """С 04.01.2027 ISO-чётность со сдвигом расходится с вузовской.

    До января они совпадали случайно (якорь 31.08.2026 + PARITY_OFFSET=1),
    поэтому баг не проявлялся. Дальше расписание инвертировалось бы:
    пара с пометкой «ч.» показывалась в нечётную неделю вуза, а в свою
    неделю день был пустым.
    """
    import asyncio
    import datetime as dt
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from infrastructure.database.models import Base, BaseLesson
    from infrastructure.database.repo.requests import RequestsRepo
    from tgbot.services import sync_vuz
    from tgbot.services.schedule_layer import get_day_slots

    async def scenario():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        pool = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with pool() as db:
                repo = RequestsRepo(db)
                await sync_vuz.set_anchor(repo, dt.date(2026, 8, 31))
                db.add(BaseLesson(group="ГД-26@vuz", week_parity="EVEN",
                                  weekday=1, para=1, subject="История",
                                  teacher="", room="", weeks="", source="vuz"))
                await db.commit()

                # 11.01.2027 — неделя 20 (чётная у вуза), ISO со сдвигом даёт ODD.
                even_vuz = dt.date(2027, 1, 11)
                # 04.01.2027 — неделя 19 (нечётная у вуза), ISO даёт EVEN.
                odd_vuz = dt.date(2027, 1, 4)
                assert sync_vuz.vuz_week(even_vuz) == 20
                assert sync_vuz.vuz_week(odd_vuz) == 19

                assert len(await get_day_slots(repo, "ГД-26@vuz", even_vuz)) == 1
                assert await get_day_slots(repo, "ГД-26@vuz", odd_vuz) == []
        finally:
            await engine.dispose()

    asyncio.get_event_loop_policy().new_event_loop().run_until_complete(scenario())
