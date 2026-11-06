"""Чат можно отвязать (план 085).

ChatRepo умел только писать и читать. Бота выгнали из группы — запись
осталась навсегда, и рассылка каждый раз пыталась туда писать и
логировала TelegramForbiddenError. На проде чатов 0, дефект латентный,
но первое же подключение упиралось в него.

Сделано и то, и другое, как просил план: кнопка на случай «админ
ошибся группой» и обработчик my_chat_member на случай выгона.
"""
import asyncio
import inspect

from tgbot.handlers import admin as admin_mod
from tgbot.middlewares.database import DatabaseMiddleware


def _make_repo(tmp_path):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from infrastructure.database.models import Base
    from infrastructure.database.repo.requests import RequestsRepo
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/db.sqlite")
    return engine, async_sessionmaker(engine, expire_on_commit=False), RequestsRepo, Base


def test_remove_deletes_chat(tmp_path):
    async def body():
        engine, sf, RequestsRepo, Base = _make_repo(tmp_path)
        async with engine.begin() as c:
            await c.run_sync(Base.metadata.create_all)
        try:
            async with sf() as sess:
                repo = RequestsRepo(sess)
                await repo.chats.set_group(-100123, "Группа", "ДП-26")
                assert len(await repo.chats.get_all()) == 1
                await repo.chats.remove(-100123)
                assert await repo.chats.get_all() == []
        finally:
            await engine.dispose()

    asyncio.run(body())


def test_remove_missing_is_silent(tmp_path):
    """Повторная отвязка не падает."""
    async def body():
        engine, sf, RequestsRepo, Base = _make_repo(tmp_path)
        async with engine.begin() as c:
            await c.run_sync(Base.metadata.create_all)
        try:
            async with sf() as sess:
                repo = RequestsRepo(sess)
                await repo.chats.remove(-100999)
                assert await repo.chats.get_all() == []
        finally:
            await engine.dispose()

    asyncio.run(body())


def test_remove_keeps_others(tmp_path):
    async def body():
        engine, sf, RequestsRepo, Base = _make_repo(tmp_path)
        async with engine.begin() as c:
            await c.run_sync(Base.metadata.create_all)
        try:
            async with sf() as sess:
                repo = RequestsRepo(sess)
                await repo.chats.set_group(-1, "A", "Г-1")
                await repo.chats.set_group(-2, "Б", "Г-2")
                await repo.chats.remove(-1)
                left = await repo.chats.get_all()
                assert [c.id for c in left] == [-2]
        finally:
            await engine.dispose()

    asyncio.run(body())


def test_admin_screen_has_unlink_button():
    body = inspect.getsource(admin_mod._chats_kb)
    assert "unchat" in body


def test_unlink_callback_registered():
    assert admin_mod.cb_adm_unchat is not None


def test_kick_handler_marks_status():
    """Выгон не удаляет строку, а помечает: экран должен показать «выгнали»."""
    body = inspect.getsource(admin_mod.on_bot_left_chat)
    assert "chats.set_status" in body


def test_kick_handler_only_left_or_kicked():
    """Помечаем «бота нет» только при left/kicked.

    restricted значит «бот в чате, но с ограничениями» — его записывать
    в выгнанные нельзя.
    """
    body = inspect.getsource(admin_mod.on_bot_left_chat)
    line = next(l for l in body.splitlines() if '"left"' in l)
    assert '"kicked"' in line, line
    assert "restricted" not in line, line


def test_added_handler_records_chat():
    """На добавление в чат бот тоже реагирует — иначе он не узнает,
    где его уже добавили."""
    body = inspect.getsource(admin_mod.on_bot_left_chat)
    assert "chats.touch" in body
    assert '"administrator"' in body or '"member"' in body


def test_middleware_registered_for_chat_member():
    import main
    assert "my_chat_member" in inspect.getsource(main.register_global_middlewares)


def test_middleware_survives_no_from_user():
    """Событие чата без from_user не должно падать на get_or_create_user."""
    body = inspect.getsource(DatabaseMiddleware.__call__)
    assert "from_user is None" in body
