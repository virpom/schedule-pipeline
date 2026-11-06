"""Экран «Все группы»: по размеру, раздельно, по страницам.

Раньше это был один плоский список вперемешку — вуз и колледж, по
алфавиту, все 129 групп одной простынёй. Найти, где больше людей, было
нельзя, а на телефоне список не влезал в экран.

Проверяем три вещи, которые админ делает руками:
  1. крупные группы наверху;
  2. можно оставить только колледж или только вуз;
  3. по страницам ходит и последняя не пустая.
"""
import asyncio

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from infrastructure.database.models import Base, Chat, User
from infrastructure.database.repo.requests import RequestsRepo


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


async def make_env():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def seed_groups(pool, sizes: dict[str, int]) -> None:
    """Завести группы заданного размера."""
    uid = 1000
    async with pool() as db:
        for group, n in sizes.items():
            for _ in range(n):
                db.add(User(id=uid, full_name=f"Студент {uid}", role="student",
                            group=group, subscribed=True, bell_detail="brief",
                            bell_mode="off", send_image=False))
                uid += 1
        await db.commit()


def labels(kb) -> list[str]:
    return [b.text for row in kb.inline_keyboard for b in row]


def test_sorted_by_size_desc():
    async def body():
        engine, pool = await make_env()
        try:
            await seed_groups(pool, {"МАЛ-26": 2, "БОЛЬ-26": 9, "СРЕД-25": 5})
            async with pool() as db:
                from tgbot.handlers.admin import _build_stats_groups
                _, kb = await _build_stats_groups(RequestsRepo(db))
                got = [x for x in labels(kb) if "чел" in x]
                assert got[0].startswith("🎓 БОЛЬ-26"), got
                assert "СРЕД-25" in got[1], got
                assert "МАЛ-26" in got[2], got
        finally:
            await engine.dispose()

    run(body())


def test_filter_college_only():
    async def body():
        engine, pool = await make_env()
        try:
            await seed_groups(pool, {"ДП-26": 3, "ЭК-26@vuz": 4})
            async with pool() as db:
                from tgbot.handlers.admin import _build_stats_groups
                _, kb = await _build_stats_groups(RequestsRepo(db), 0, "college")
                got = [x for x in labels(kb) if "чел" in x]
                assert len(got) == 1 and "ДП-26" in got[0], got
                text, _ = await _build_stats_groups(RequestsRepo(db), 0, "college")
                assert "Колледж" in text
        finally:
            await engine.dispose()

    run(body())


def test_filter_vuz_only():
    async def body():
        engine, pool = await make_env()
        try:
            await seed_groups(pool, {"ДП-26": 3, "ЭК-26@vuz": 4})
            async with pool() as db:
                from tgbot.handlers.admin import _build_stats_groups
                _, kb = await _build_stats_groups(RequestsRepo(db), 0, "vuz")
                got = [x for x in labels(kb) if "чел" in x]
                assert len(got) == 1 and "ЭК-26" in got[0], got
                # Служебный суффикс @vuz админу не показываем.
                assert "@vuz" not in got[0], got
        finally:
            await engine.dispose()

    run(body())


def test_pagination_spreads_groups():
    async def body():
        engine, pool = await make_env()
        try:
            await seed_groups(pool, {f"Г-{i:02d}": 1 for i in range(25)})
            async with pool() as db:
                from tgbot.handlers.admin import GROUPS_PER_PAGE, _build_stats_groups
                _, kb0 = await _build_stats_groups(RequestsRepo(db), 0, "")
                show = [x for x in labels(kb0) if "чел" in x]
                assert len(show) == GROUPS_PER_PAGE, show
                assert any("/" in x for x in labels(kb0)), "нет номера страницы"
        finally:
            await engine.dispose()

    run(body())


def test_last_page_not_empty():
    """Ровно 20 групп при странице в 10 — вторая страница не пустая."""
    async def body():
        engine, pool = await make_env()
        try:
            await seed_groups(pool, {f"Г-{i:02d}": 1 for i in range(20)})
            async with pool() as db:
                from tgbot.handlers.admin import _build_stats_groups
                _, kb = await _build_stats_groups(RequestsRepo(db), 1, "")
                show = [x for x in labels(kb) if "чел" in x]
                assert len(show) == 10, show
        finally:
            await engine.dispose()

    run(body())


def test_no_group_button_present():
    """Люди без группы не пропадают из админки."""
    async def body():
        engine, pool = await make_env()
        try:
            await seed_groups(pool, {"ДП-26": 2})
            async with pool() as db:
                db.add(User(id=99, full_name="Без группы", role="student",
                            group=None, subscribed=False, bell_detail="brief",
                            bell_mode="off", send_image=False))
                await db.commit()
                from tgbot.handlers.admin import _build_stats_groups
                _, kb = await _build_stats_groups(RequestsRepo(db))
                assert any("Без группы" in x for x in labels(kb)), labels(kb)
        finally:
            await engine.dispose()

    run(body())


def test_chats_screen_shows_status():
    async def body():
        engine, pool = await make_env()
        try:
            async with pool() as db:
                db.add(Chat(id=-100, title="ДП-26 чат", group="ДП-26", status="member"))
                db.add(Chat(id=-200, title="Старый чат", group=None, status="kicked"))
                await db.commit()
                from tgbot.handlers.admin import _chats_text
                text = await _chats_text(RequestsRepo(db))
                assert "бот в чате" in text, text
                assert "выгнали" in text, text
                assert "группа не задана" in text, text
        finally:
            await engine.dispose()

    run(body())


def test_chat_touch_records_new_chat():
    async def body():
        engine, pool = await make_env()
        try:
            async with pool() as db:
                repo = RequestsRepo(db)
                await repo.chats.touch(-100, "Новая группа")
                chats = await repo.chats.get_all()
                assert len(chats) == 1
                assert chats[0].status == "member"
                assert chats[0].title == "Новая группа"
                assert chats[0].group is None
        finally:
            await engine.dispose()

    run(body())


def test_chat_touch_keeps_existing_group():
    """Повторное добавление не стирает привязанную группу."""
    async def body():
        engine, pool = await make_env()
        try:
            async with pool() as db:
                repo = RequestsRepo(db)
                await repo.chats.set_group(-100, "ДП-26 чат", "ДП-26")
                await repo.chats.touch(-100, "ДП-26 чат")
                chats = await repo.chats.get_all()
                assert chats[0].group == "ДП-26"
        finally:
            await engine.dispose()

    run(body())


def test_status_survives_kick():
    """Выгон не удаляет чат — иначе он молча исчезнет из списка."""
    async def body():
        engine, pool = await make_env()
        try:
            async with pool() as db:
                repo = RequestsRepo(db)
                await repo.chats.touch(-100, "Чат")
                await repo.chats.set_status(-100, "kicked")
                chats = await repo.chats.get_all()
                assert len(chats) == 1
                assert chats[0].status == "kicked"
        finally:
            await engine.dispose()

    run(body())
