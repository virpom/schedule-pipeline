"""Сессия пересоздаёт соединение после сетевого сбоя.

Прод, 10.11.2026: контейнер простоял 14 часов, каждые 5 секунд
«Connection reset by peer» — 37 попыток подряд. При этом `aiohttp` из
того же контейнера в тот же момент получал 200 пять раз из пяти:
сеть была жива, мёртвым был сокет внутри бота.

Причина в aiogram: `_should_reset_connector` выставляется в False при
первом создании сессии и больше не трогается. Ошибка сети не сбрасывает
его, поэтому каждая следующая попытка идёт в тот же мёртвый коннектор.
Помогал только перезапуск процесса.

Тесты держат два свойства:
  1. после TelegramNetworkError коннектор помечен на пересоздание;
  2. успешный запрос флаг не трогает (иначе сессия рвётся на ровном месте).
"""
import asyncio

import pytest
from aiogram.exceptions import TelegramNetworkError

from tgbot.session import ReconnectingSession


class _FakeMethod:
    """Минимальный TelegramMethod: сессии нужен только __api_method__."""

    __api_method__ = "getMe"


class _FakeBot:
    token = "42:TEST"


def _session() -> ReconnectingSession:
    return ReconnectingSession()


def _network_error() -> TelegramNetworkError:
    return TelegramNetworkError(method=_FakeMethod(), message="Connection reset by peer")


def test_reset_after_network_error(monkeypatch):
    """Сбой сети помечает коннектор на пересоздание."""
    session = _session()

    async def boom(self, bot, method, timeout=None):
        raise _network_error()

    monkeypatch.setattr(
        "aiogram.client.session.aiohttp.AiohttpSession.make_request", boom
    )
    session._should_reset_connector = False

    with pytest.raises(TelegramNetworkError):
        asyncio.run(session.make_request(_FakeBot(), _FakeMethod()))

    assert session._should_reset_connector is True


def test_no_reset_on_success(monkeypatch):
    """Успешный запрос флаг не поднимает — иначе рвём живое соединение."""
    session = _session()

    async def fine(self, bot, method, timeout=None):
        return {"ok": True}

    monkeypatch.setattr(
        "aiogram.client.session.aiohttp.AiohttpSession.make_request", fine
    )
    session._should_reset_connector = False

    assert asyncio.run(session.make_request(_FakeBot(), _FakeMethod())) == {"ok": True}
    assert session._should_reset_connector is False


def test_dns_cache_shorter_than_aiogram_default():
    """DNS кеш короче часа: fakeip-записи живут в sing-box, не в aiohttp."""
    session = _session()
    assert session._connector_init["ttl_dns_cache"] <= 60


def test_private_flag_still_exists():
    """Флаг приватный. Если aiogram его переименует — узнать сразу, а не на проде."""
    session = _session()
    assert hasattr(session, "_should_reset_connector"), (
        "aiogram убрал _should_reset_connector: переподключение в tgbot/session.py "
        "перестало работать, нужно переписать под новый API"
    )
