"""Заблокировавший бота снимается с подписки (план 099).

send_message ловил TelegramForbiddenError и только логировал. Возвращал
False, но никто на результат не смотрел: broadcast_schedule считал
только успешные, а users.subscribed не менялся.

Заблокировавший оставался в get_subscribed() навсегда. На проде таких
было 11 из 228 — каждый цикл бот тратил на них 11 запросов и писал 11
строк в лог, вытесняя полезные записи.
"""
import asyncio
from types import SimpleNamespace

import pytest
from aiogram import exceptions

from tgbot.services import broadcaster


def _bot(raise_exc):
    async def send_message(*a, **k):
        if raise_exc:
            raise raise_exc
        return SimpleNamespace(message_id=1)

    async def send_photo(*a, **k):
        if raise_exc:
            raise raise_exc
        return SimpleNamespace(message_id=1, photo=[SimpleNamespace(file_id="f")])

    return SimpleNamespace(send_message=send_message, send_photo=send_photo)


@pytest.fixture(autouse=True)
def _clear_retry():
    broadcaster._retry["max"] = 0.0
    broadcaster._file_ids.clear()


def test_send_message_reports_blocked():
    blocked = []
    ok = asyncio.run(broadcaster.send_message(
        _bot(exceptions.TelegramForbiddenError(method=None, message="blocked")),
        42, "текст", blocked=blocked))
    assert ok is False
    assert blocked == [42], blocked


def test_send_photo_reports_blocked():
    blocked = []
    ok = asyncio.run(broadcaster.send_photo(
        _bot(exceptions.TelegramForbiddenError(method=None, message="blocked")),
        42, "/tmp/x.jpg", "подпись", blocked=blocked))
    assert ok is False
    assert blocked == [42], blocked


def test_broadcast_collects_blocked():
    blocked = []
    bot = _bot(exceptions.TelegramForbiddenError(method=None, message="blocked"))
    asyncio.run(broadcaster.broadcast_schedule(bot, [(42, "текст", None)],
                                               rate=100, blocked=blocked))
    assert blocked == [42], blocked


def test_blocked_not_retried():
    """Повторять заблокировавшему бессмысленно — он не в failed."""
    calls = []

    async def send_message(uid, text, **k):
        calls.append(uid)
        raise exceptions.TelegramForbiddenError(method=None, message="blocked")

    bot = SimpleNamespace(send_message=send_message, send_photo=send_message)
    blocked = []
    asyncio.run(broadcaster.broadcast_schedule(bot, [(42, "текст", None)],
                                               rate=100, blocked=blocked))
    assert calls == [42], f"заблокировавшему отправили {len(calls)} раза"


def test_ordinary_failure_still_retried():
    """Не-Forbidden по-прежнему повторяется — это временный сбой."""
    calls = []

    async def send_message(uid, text, **k):
        calls.append(uid)
        raise exceptions.TelegramAPIError(method=None, message="flaky")

    bot = SimpleNamespace(send_message=send_message, send_photo=send_message)
    blocked = []
    asyncio.run(broadcaster.broadcast_schedule(bot, [(42, "текст", None)],
                                               rate=100, blocked=blocked))
    assert len(calls) == 2, calls
    assert blocked == [], blocked


def test_success_not_blocked():
    blocked = []
    ok = asyncio.run(broadcaster.send_message(_bot(None), 42, "текст", blocked=blocked))
    assert ok is True
    assert blocked == []


def test_poller_unsubscribes_blocked():
    """Поллер зовёт set_subscribed(False) для каждого из blocked."""
    import inspect
    from tgbot.services import poller
    body = inspect.getsource(poller.notify_new_schedule)
    assert "set_subscribed(uid, False)" in body, body[-600:]
    assert "blocked=blocked" in body
