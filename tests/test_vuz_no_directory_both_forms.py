"""План 170: без справочника групп одна форма вуза сносила обе.

`replace_vuz_lessons` и `replace_vuz_changes` выбирали, что удалять, по
справочнику `vuz_group`. Справочника нет (функцию позвали раньше
`replace_vuz_groups`) — уходили в `else` и удаляли все строки вуза по
`source == 'vuz'`, то есть и чужую форму. Комментарий обещал «берём
группы из самого файла», но у функции их не было.

В проде ветка недостижима: `sync_once` пишет справочник первым. Но
контракт функции её допускал, и локальный вызов без справочника (так
делают тесты и будущий код) молча терял целую форму обучения.

Проверяем на паре «полный / очно-заочный» с пустым справочником: чужая
форма должна пережить вызов, а своя — обновиться.
"""
import asyncio
import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from infrastructure.database.models import Base, BaseLesson, Substitution
from infrastructure.database.repo.requests import RequestsRepo
from parsers import vuz
from tgbot.services import sync_vuz


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


async def make_pool():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _lessons(repo) -> dict[str, str]:
    rows = (await repo.session.execute(select(BaseLesson))).scalars().all()
    return {r.group: r.subject for r in rows}


async def _subs(repo) -> dict[str, str]:
    rows = (await repo.session.execute(select(Substitution))).scalars().all()
    return {r.group: r.subject for r in rows}


def _seed_lessons(repo):
    return sync_vuz.replace_vuz_lessons(repo, [
        vuz.VuzLesson("ЭК-23@vuz", 1, 1, "ANY", "Очная старая", weeks=(1,)),
        vuz.VuzLesson("ПС-23оз@vuz", 1, 1, "ANY", "Заочная старая", weeks=(1,)),
    ], "full")


def test_lessons_without_directory_keep_other_form():
    """Справочник пуст: очная не имеет права трогать очно-заочную."""
    async def scenario():
        engine, pool = await make_pool()
        try:
            async with pool() as db:
                repo = RequestsRepo(db)
                assert (await _lessons(repo)) == {}
                await _seed_lessons(repo)

                # Вызов без справочника — как в тестах и в старом порядке.
                n = await sync_vuz.replace_vuz_lessons(repo, [
                    vuz.VuzLesson("ЭК-23@vuz", 1, 2, "ANY", "Новая", weeks=(1,)),
                ], "full")
                assert n == 1

                subjects = await _lessons(repo)
                assert subjects.get("ПС-23оз@vuz") == "Заочная старая", (
                    f"форма part снесена вызовом для full: {subjects}")
                assert subjects.get("ЭК-23@vuz") == "Новая"
        finally:
            await engine.dispose()
    run(scenario())


def test_lessons_without_directory_still_clean_own_form():
    """Свои строки чистятся даже без справочника — иначе чинилось бы не то."""
    async def scenario():
        engine, pool = await make_pool()
        try:
            async with pool() as db:
                repo = RequestsRepo(db)
                assert (await sync_vuz.replace_vuz_lessons(repo, [
                    vuz.VuzLesson("ЭК-23@vuz", 1, 1, "ANY", "Протухшая",
                                  weeks=(1,)),
                ], "full")) == 1
                await sync_vuz.replace_vuz_lessons(repo, [
                    vuz.VuzLesson("ЭК-23@vuz", 1, 2, "ANY", "Свежая", weeks=(1,)),
                ], "full")
                assert await _lessons(repo) == {"ЭК-23@vuz": "Свежая"}
        finally:
            await engine.dispose()
    run(scenario())


def test_changes_without_directory_keep_other_form():
    """Замены: та же ветка сносила все формы по source == 'vuz'."""
    async def scenario():
        engine, pool = await make_pool()
        try:
            async with pool() as db:
                repo = RequestsRepo(db)
                await sync_vuz.replace_vuz_changes(repo, [
                    vuz.VuzChange("ЭК-23@vuz", datetime.date(2026, 11, 9), 1,
                                  "Очная старая"),
                    vuz.VuzChange("ПС-23оз@vuz", datetime.date(2026, 11, 9), 1,
                                  "Заочная старая"),
                ], "full")

                await sync_vuz.replace_vuz_changes(repo, [
                    vuz.VuzChange("ЭК-23@vuz", datetime.date(2026, 11, 10), 2,
                                  "Новая"),
                ], "full")

                subjects = await _subs(repo)
                assert subjects.get("ПС-23оз@vuz") == "Заочная старая", (
                    f"замены part снесены вызовом для full: {subjects}")
                assert subjects.get("ЭК-23@vuz") == "Новая"
        finally:
            await engine.dispose()
    run(scenario())
