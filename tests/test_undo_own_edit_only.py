"""«Откатить» снимает только свою правку (план 086).

cb_undo звал get_last(group) без автора. get_last умеет фильтровать по
user_id, но параметр не передавался — значит None, значит фильтра нет,
и староста Б, ничего не делавший, откатывал правку старосты А и видел
«Возвращено: <предмет>» как будто это его.

На проде два старосты на одну группу (schedule_editor, 'ДП-26'),
то есть сценарий готов сработать на первом же откате. schedule_edit
пока 0 строк — правок не было.
"""
import asyncio
import inspect

from tgbot.handlers import editor as editor_mod


def _repo(tmp_path):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from infrastructure.database.models import Base
    from infrastructure.database.repo.requests import RequestsRepo
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/db.sqlite")
    return engine, async_sessionmaker(engine, expire_on_commit=False), RequestsRepo, Base


async def _seed(tmp_path):
    engine, sf, RequestsRepo, Base = _repo(tmp_path)
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    return engine, sf, RequestsRepo


def test_get_last_filters_by_author(tmp_path):
    async def body():
        engine, sf, RequestsRepo = await _seed(tmp_path)
        try:
            async with sf() as sess:
                repo = RequestsRepo(sess)
                await repo.edit_log.log("ДП-26", "base", "edit", user_id=100,
                                        para=3, old_value={"subject": "А"},
                                        new_value={"subject": "Б"})
                mine = await repo.edit_log.get_last("ДП-26", 100)
                other = await repo.edit_log.get_last("ДП-26", 200)
                assert mine is not None and mine.user_id == 100
                assert other is None, "чужая правка попала в свой откат"
        finally:
            await engine.dispose()

    asyncio.run(body())


def test_get_last_returns_newest_own(tmp_path):
    """Своя правка берётся даже если чужая свежее."""
    async def body():
        engine, sf, RequestsRepo = await _seed(tmp_path)
        try:
            async with sf() as sess:
                repo = RequestsRepo(sess)
                await repo.edit_log.log("ДП-26", "base", "edit", user_id=100, para=1)
                await repo.edit_log.log("ДП-26", "base", "edit", user_id=200, para=2)
                got = await repo.edit_log.get_last("ДП-26", 100)
                assert got is not None
                assert got.para == 1, f"взята чужая правка: пара {got.para}"
        finally:
            await engine.dispose()

    asyncio.run(body())


def test_get_last_without_user_still_works(tmp_path):
    """Старое поведение не сломали: без user_id — последняя по группе."""
    async def body():
        engine, sf, RequestsRepo = await _seed(tmp_path)
        try:
            async with sf() as sess:
                repo = RequestsRepo(sess)
                await repo.edit_log.log("ДП-26", "base", "edit", user_id=100, para=1)
                await repo.edit_log.log("ДП-26", "base", "edit", user_id=200, para=2)
                got = await repo.edit_log.get_last("ДП-26")
                assert got.para == 2
        finally:
            await engine.dispose()

    asyncio.run(body())


def test_undo_passes_author():
    body = inspect.getsource(editor_mod.cb_undo)
    assert "get_last(group, cb.from_user.id)" in body, "автор не передан"


def test_undo_message_explains():
    body = inspect.getsource(editor_mod.cb_undo)
    assert "своих правок нет" in body


def test_journal_marks_foreign_edits():
    body = inspect.getsource(editor_mod.cb_log)
    assert "👤 другой" in body
