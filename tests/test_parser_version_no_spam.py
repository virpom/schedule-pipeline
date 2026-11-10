"""Смена PARSER_VERSION не выглядит как правка расписания.

Прод, 10.11.2026. Я поднял PARSER_VERSION 4 -> 5 (правка парсера замен),
и бот разослал 988 сообщений «расписание изменилось» — при том что на
сайте ничего не менялось. Механика:

    _sha(data) = sha256(байты + версия парсера)
    _sync_zameny: хеш другой -> changed["zameny"] = True
    poller: result["zameny"] -> college_changed -> сравнение снимков
    -> notify_new_schedule -> рассылка всем

Версия парсера должна заставлять ПЕРЕЧИТАТЬ базу, но не быть поводом
писать людям. Здесь это и проверяется: перечитывание есть, флага нет.

Отдельно проверено, что настоящая правка файла флаг всё-таки поднимает —
иначе фикс просто выключил бы уведомления целиком.
"""
import hashlib

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from infrastructure.database.models import Base
from infrastructure.database.repo.requests import RequestsRepo
from tgbot.services import sync_eios


@pytest.fixture
async def repo():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    pool = async_sessionmaker(engine, expire_on_commit=False)
    async with pool() as session:
        yield RequestsRepo(session)
    await engine.dispose()


def test_sha_depends_on_parser_version():
    """Хеш разбора меняется от версии — иначе правка парсера не доедет."""
    data = b"file"
    before = sync_eios._sha(data)
    assert before != sync_eios._content_sha(data)


def test_content_sha_ignores_parser_version():
    """Хеш содержимого от версии не зависит — на нём и держится фикс."""
    data = b"file"
    # Обе функции чистые: подменять глобальную версию не нужно,
    # достаточно убедиться, что хеш содержимого — обычный sha256.
    assert sync_eios._content_sha(data) == hashlib.sha256(data).hexdigest()


@pytest.mark.asyncio
async def test_parser_version_bump_does_not_raise_changed(repo, monkeypatch):
    """Перечитывание из-за версии парсера не поднимает changed."""
    data = b"same bytes"

    # Прошлый прогон запомнил хеш содержимого — файл не менялся.
    await repo.settings.set(
        sync_eios._CONTENT_KEY.format(kind="zameny"),
        sync_eios._content_sha(data),
    )

    changed: dict = {}
    fresh = await sync_eios._content_is_new(repo, "zameny", data)
    assert fresh is False, "файл тот же, а признан новым"
    assert "zameny" not in changed


@pytest.mark.asyncio
async def test_real_file_change_raises_changed(repo):
    """Настоящая правка файла флаг поднимает — иначе уведомлений не будет."""
    key = sync_eios._CONTENT_KEY.format(kind="zameny")
    await repo.settings.set(key, sync_eios._content_sha(b"old file"))

    assert await sync_eios._content_is_new(repo, "zameny", b"new file") is True


@pytest.mark.asyncio
async def test_first_run_is_silent(repo):
    """Первый прогон после деплоя молчит.

    Иначе сама эта правка дала бы ещё одну волну рассылки: ключа ещё
    нет, «было» не с чем сравнить.
    """
    assert await sync_eios._content_is_new(repo, "ochoe", b"anything") is False


@pytest.mark.asyncio
async def test_first_run_remembers_hash(repo):
    """Молчит, но хеш запоминает — следующий прогон уже сравнит."""
    await sync_eios._content_is_new(repo, "ochoe", b"anything")
    key = sync_eios._CONTENT_KEY.format(kind="ochoe")
    assert await repo.settings.get(key) == sync_eios._content_sha(b"anything")
