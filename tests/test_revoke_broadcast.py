"""План 104: id отправленного запоминается — иначе рассылку не отозвать.

`broadcaster.send_message` выбрасывал ответ Bot API, а `bot.send_message`
возвращает `types.Message` с `message_id`. Другого способа узнать id уже
отправленного сообщения у Bot API нет (`getUpdates` отдаёт только
входящие), поэтому 26.10.2026 ушедшие 3220 сообщений отозвать было нечем.

Здесь проверяется то, что делала рассылка на старом коде: правильная
отправка, но `sent_to` остаётся пустым.
"""
import datetime
from types import SimpleNamespace

import pytest
from aiogram import exceptions
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from infrastructure.database.models import Base
from infrastructure.database.repo.requests import RequestsRepo
from tgbot.services import broadcaster


class _Bot:
    """Бот, который помнит, что ему велели удалить."""

    def __init__(self, next_message_id=100):
        self.sent = []
        self.deleted = []
        self.fail_delete = set()
        self._id = next_message_id

    async def send_message(self, chat_id, text, **kw):
        self._id += 1
        if isinstance(chat_id, int) and chat_id < 0:
            raise exceptions.TelegramForbiddenError(method=None, message="blocked")
        self.sent.append(chat_id)
        return SimpleNamespace(message_id=self._id,
                               chat=SimpleNamespace(id=chat_id))

    async def send_photo(self, chat_id, photo, caption=None, **kw):
        return await self.send_message(chat_id, caption or "")

    async def delete_message(self, chat_id, message_id):
        if (chat_id, message_id) in self.fail_delete:
            raise exceptions.TelegramBadRequest(
                method=None, message="message can't be deleted for everyone")
        self.deleted.append((chat_id, message_id))


@pytest.fixture
async def repo():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    pool = async_sessionmaker(engine, expire_on_commit=False)
    async with pool() as session:
        yield RequestsRepo(session)
    await engine.dispose()


@pytest.mark.asyncio
async def test_broadcast_many_collects_message_ids():
    broadcaster._retry["max"] = 0.0
    bot = _Bot()
    sent_to: list = []
    await broadcaster.broadcast_many(bot, [(1, "a"), (2, "b")], rate=100,
                                     sent_to=sent_to)
    assert len(sent_to) == 2, f"id не сохранены: {sent_to}"
    assert [c for c, _ in sent_to] == [1, 2]
    assert all(isinstance(m, int) and m > 0 for _, m in sent_to)


@pytest.mark.asyncio
async def test_broadcast_schedule_collects_message_ids():
    broadcaster._retry["max"] = 0.0
    bot = _Bot()
    sent_to: list = []
    items = [(1, "a", None), (2, "b", "photo.png")]
    await broadcaster.broadcast_schedule(bot, items, rate=100, sent_to=sent_to)
    assert len(sent_to) == 2, f"id не сохранены: {sent_to}"


@pytest.mark.asyncio
async def test_failed_recipient_stores_no_id():
    """Заблокировавший бота ничего не получил — удалять нечего."""
    broadcaster._retry["max"] = 0.0
    bot = _Bot()
    sent_to: list = []
    await broadcaster.broadcast_many(bot, [(1, "a"), (-5, "b")], rate=100,
                                     sent_to=sent_to)
    assert [c for c, _ in sent_to] == [1]


@pytest.mark.asyncio
async def test_batch_roundtrip_and_latest(repo):
    await repo.sent_messages.add_batch([(1, 10, "broadcast"), (2, 11, "broadcast")])
    moment, rows = await repo.sent_messages.latest_batch("broadcast")
    assert sorted(rows) == [(1, 10), (2, 11)]
    assert await repo.sent_messages.count() == 2
    assert await repo.sent_messages.latest_batch("schedule") is None


@pytest.mark.asyncio
async def test_purge_old_keeps_recent(repo):
    """Bot API не удалит сообщение старше 48 часов — id старше бесполезны."""
    old = datetime.datetime.now() - datetime.timedelta(hours=50)
    fresh = datetime.datetime.now()
    from infrastructure.database.models import SentMessage

    repo.session.add_all([
        SentMessage(chat_id=1, message_id=1, kind="schedule", created_at=old),
        SentMessage(chat_id=2, message_id=2, kind="schedule", created_at=fresh),
    ])
    await repo.session.commit()
    removed = await repo.sent_messages.purge_older(48)
    assert removed == 1
    _, rows = await repo.sent_messages.latest_batch("schedule")
    assert rows == [(2, 2)]


@pytest.mark.asyncio
async def test_revoke_deletes_everything_and_survives_errors():
    from tgbot.services import revoke

    bot = _Bot()
    bot.fail_delete.add((2, 11))
    removed, failed = await revoke.revoke(
        bot, [(1, 10), (2, 11), (3, 12)], rate=1000)
    assert removed == 2 and failed == 1
    assert (1, 10) in bot.deleted and (3, 12) in bot.deleted, (
        "одна ошибка оборвала отзыв")


def test_admin_broadcast_stores_ids():
    """Обработчик ручной рассылки обязан сохранить id, а не выбросить."""
    from tgbot.handlers import admin
    import inspect

    src = inspect.getsource(admin._report_broadcast)
    assert "sent_to" in src and "sent_messages.add_batch" in src, (
        "id рассылки не сохраняются")


def test_admin_has_revoke_button():
    from tgbot.handlers import admin

    assert "adm:revoke" in str(admin._admin_kb().model_dump()), (
        "кнопки отзыва нет в админ-меню")
