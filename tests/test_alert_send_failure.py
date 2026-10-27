"""Тревога не теряется, если отправка не удалась.

План 050. `alert()` писала хеш в `setting` ДО отправки, а `_send`
глотала `TelegramAPIError` и возвращала управление нормально. Если
админ заблокировал бота:

  1. digest записан;
  2. отправка упала, только log.warning;
  3. следующий цикл: текст тот же → digest совпал → return.

Тревога не дошла бы никогда, а система считала бы, что доложила.
"""

import pytest
from aiogram.exceptions import TelegramForbiddenError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from infrastructure.database.models import Base
from infrastructure.database.repo.requests import RequestsRepo
from tgbot.services import alerts


class _Config:
    class tg_bot:
        admin_ids = [111, 222]


class _Bot:
    """Бот, который падает на отправке."""

    def __init__(self, fail=True):
        self.fail = fail
        self.sent = []

    async def send_message(self, admin_id, text):
        if self.fail:
            raise TelegramForbiddenError(method=None, message="bot was blocked")
        self.sent.append((admin_id, text))


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
async def test_failed_send_does_not_mark_as_reported(repo):
    """Отправка упала — хеш не записан, тревога повторится."""
    bot = _Bot(fail=True)
    await alerts.alert(bot, repo, _Config, "structure", "схема сломалась")
    stored = await repo.settings.get(alerts.ALERT_KEY.format(kind="structure"))
    assert not stored, "неотправленная тревога помечена как сообщённая"


@pytest.mark.asyncio
async def test_failed_send_retries_next_cycle(repo):
    """Второй цикл пробует снова и доходит, когда бот ожил."""
    bot = _Bot(fail=True)
    await alerts.alert(bot, repo, _Config, "structure", "схема сломалась")
    assert bot.sent == []

    bot.fail = False
    await alerts.alert(bot, repo, _Config, "structure", "схема сломалась")
    assert len(bot.sent) == 2, "повторная попытка не отправилась"


@pytest.mark.asyncio
async def test_successful_send_marks_and_dedupes(repo):
    """Успешная отправка записывает хеш, повтор молчит."""
    bot = _Bot(fail=False)
    await alerts.alert(bot, repo, _Config, "structure", "схема сломалась")
    assert len(bot.sent) == 2
    await alerts.alert(bot, repo, _Config, "structure", "схема сломалась")
    assert len(bot.sent) == 2, "тревога задублировалась"


@pytest.mark.asyncio
async def test_partial_delivery_counts_as_sent(repo):
    """Дошло одному из двух — считаем доставленным, спама нет."""

    class _HalfBot(_Bot):
        async def send_message(self, admin_id, text):
            if admin_id == 111:
                raise TelegramForbiddenError(method=None, message="blocked")
            self.sent.append((admin_id, text))

    bot = _HalfBot()
    await alerts.alert(bot, repo, _Config, "structure", "схема сломалась")
    assert len(bot.sent) == 1
    await alerts.alert(bot, repo, _Config, "structure", "схема сломалась")
    assert len(bot.sent) == 1, "задублировалось при частичной доставке"


@pytest.mark.asyncio
async def test_clear_keeps_state_when_send_fails(repo):
    """Не смогли сообщить о восстановлении — ключ не чистим."""
    bot = _Bot(fail=False)
    await alerts.alert(bot, repo, _Config, "structure", "схема сломалась")
    key = alerts.ALERT_KEY.format(kind="structure")
    assert await repo.settings.get(key)

    bot.fail = True
    await alerts.clear(bot, repo, _Config, "structure", "отпустило")
    assert await repo.settings.get(key), "потеряли состояние тревоги"


@pytest.mark.asyncio
async def test_clear_works_when_delivered(repo):
    bot = _Bot(fail=False)
    await alerts.alert(bot, repo, _Config, "structure", "схема сломалась")
    key = alerts.ALERT_KEY.format(kind="structure")
    await alerts.clear(bot, repo, _Config, "structure", "отпустило")
    assert not await repo.settings.get(key)
    assert any("Восстановилось" in t for _, t in bot.sent)


@pytest.mark.asyncio
async def test_send_returns_bool(repo):
    """Контракт `_send`: True только при реальной доставке."""
    assert await alerts._send(_Bot(fail=False), _Config, "текст") is True
    assert await alerts._send(_Bot(fail=True), _Config, "текст") is False
