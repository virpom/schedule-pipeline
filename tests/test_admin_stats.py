"""Статистика админки: разделение колледжа и вуза."""
import asyncio
import datetime as dt

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from infrastructure.database.models import Base, BaseLesson, CollegeLesson, Substitution, User
from infrastructure.database.repo.requests import RequestsRepo


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


async def make_env():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def user(uid, group, role="student", subscribed=True):
    return User(id=uid, full_name=f"Пользователь {uid}", role=role,
                group=group, subscribed=subscribed,
                bell_detail="brief", bell_mode="off", send_image=False)


def base(group, source, para=1):
    return BaseLesson(group=group, week_parity="ANY", weekday=1, para=para,
                      subject="Предмет", teacher="", room="",
                      weeks="", source=source)


def college(group, date):
    return CollegeLesson(date=date, group=group, para=1, para_end=1,
                         subject="Предмет", teacher="", room="",
                         source_url="", source="site", changed=False)


async def seed(pool):
    async with pool() as db:
        db.add_all([
            user(1, "ТЭ-26ФП"), user(2, "ТЭ-26ФП"), user(3, "ЭК-26-2@vuz"),
            user(4, "ЭК-26-2@vuz", subscribed=False),
            user(5, None, role="teacher"),
        ])
        db.add_all([
            base("ТЭ-26ФП", "site", para=1), base("ТЭ-26ФП", "site", para=2),
            base("ЭК-26-2@vuz", "vuz"),
            college("ТЭ-26ФП", dt.date(2026, 10, 26)),
            college("ЭК-26-2@vuz", dt.date(2026, 10, 26)),
        ])
        db.add_all([
            Substitution(date=dt.date(2026, 10, 26), group="ТЭ-26ФП", para=1,
                         action="replace", subject="Замена", teacher="", room="",
                         comment="", source="site"),
            Substitution(date=dt.date(2026, 10, 26), group="ЭК-26-2@vuz", para=1,
                         action="replace", subject="Замена", teacher="", room="",
                         comment="", source="vuz"),
        ])
        await db.commit()


def test_counts_split_by_unit():
    """Числа должны делиться: у подразделений разные источники и объёмы."""
    async def scenario():
        engine, pool = await make_env()
        try:
            await seed(pool)
            async with pool() as db:
                repo = RequestsRepo(db)
                assert await repo.base_lessons.count(vuz=True) == 1
                assert await repo.base_lessons.count(vuz=False) == 2
                assert await repo.base_lessons.count() == 3
                assert await repo.substitutions.count(vuz=True) == 1
                assert await repo.substitutions.count(vuz=False) == 1
        finally:
            await engine.dispose()
    run(scenario())


def test_stats_screen_shows_both_units():
    async def scenario():
        engine, pool = await make_env()
        try:
            await seed(pool)
            async with pool() as db:
                from tgbot.handlers.admin import _build_stats
                text, kb = await _build_stats(RequestsRepo(db))
                assert "Колледж" in text and "Вуз" in text
                # 2 студента колледжа, 2 вуза
                # 2 колледж + 2 вуз; преподаватель без группы не в счёт.
                assert "студентов <b>2</b>" in text
                assert "студентов <b>3</b>" not in text
                labels = [b.text for row in kb.inline_keyboard for b in row]
                assert any("Колледж" in x for x in labels)
                assert any("Вуз" in x for x in labels)
        finally:
            await engine.dispose()
    run(scenario())


def test_stats_unit_college_excludes_vuz():
    async def scenario():
        engine, pool = await make_env()
        try:
            await seed(pool)
            async with pool() as db:
                from tgbot.handlers.admin import _build_stats_unit
                text, _ = await _build_stats_unit(RequestsRepo(db), "college")
                # 2 студента колледжа; преподаватель без группы не в счёт.
                assert "Студентов: <b>2</b>" in text
                assert "Пар в базе: <b>2</b>" in text
                assert "ЭК-26-2" not in text
        finally:
            await engine.dispose()
    run(scenario())


def test_stats_unit_vuz_shows_forms():
    async def scenario():
        engine, pool = await make_env()
        try:
            await seed(pool)
            async with pool() as db:
                from tgbot.handlers.admin import _build_stats_unit
                text, _ = await _build_stats_unit(RequestsRepo(db), "vuz")
                assert "Студентов: <b>2</b>" in text
                assert "Пар в базе: <b>1</b>" in text
        finally:
            await engine.dispose()
    run(scenario())


def test_groups_screen_marks_unit():
    async def scenario():
        engine, pool = await make_env()
        try:
            await seed(pool)
            async with pool() as db:
                from tgbot.handlers.admin import _build_stats_groups
                text, kb = await _build_stats_groups(RequestsRepo(db))
                labels = [b.text for row in kb.inline_keyboard for b in row]
                assert any(x.startswith("🏛") for x in labels)
                assert any(x.startswith("🎓") for x in labels)
                # Вуз в кнопках без служебного суффикса.
                assert any("ЭК-26-2" in x and "@vuz" not in x for x in labels)
                assert "Всего <b>2</b>" in text
        finally:
            await engine.dispose()
    run(scenario())
