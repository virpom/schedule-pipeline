"""Сбои связи с Telegram — не «Ошибка в боте».

06.11 за час пришли три алерта: TelegramNetworkError в aiohttp.py:188,
TelegramRetryAfter в base.py:110, TimeoutError в impl.py:167. Ни один
не был поломкой бота: связь с api.telegram.org рвалась, флуд-контроль
срабатывал, ответ не успевал.

aiogram такие ошибки ретраит сам — студент в итоге видит расписание.
Админу же приходило «⚠️ Ошибка в боте» на каждый чих связи, и настоящую
поломку он бы пропустил среди шума.

Пользователю тоже не надо писать «Что-то пошло не так»: это сообщение
идёт по тому же оборванному каналу.
"""
import asyncio

from aiogram.exceptions import (TelegramNetworkError, TelegramRetryAfter,
                                TelegramServerError)

from tgbot.middlewares.errors import _is_transient


def test_network_error_is_transient():
    assert _is_transient(TelegramNetworkError(method=None, message="net"))


def test_retry_after_is_transient():
    assert _is_transient(TelegramRetryAfter(method=None, message="flood", retry_after=3))


def test_timeout_is_transient():
    assert _is_transient(asyncio.TimeoutError())


def test_server_error_is_transient():
    assert _is_transient(TelegramServerError(method=None, message="500"))


def test_bad_request_is_not_transient():
    """400-е остаются ошибками — там правда что-то не так."""
    from aiogram.exceptions import TelegramBadRequest
    assert not _is_transient(TelegramBadRequest(method=None, message="bad"))


# --- нет прав в чате — не «ошибка в боте» -------------------------------

def test_not_enough_rights_is_harmless():
    """06.11 20:53: «📅 Завтра» в группе, где бот не может писать."""
    from aiogram.exceptions import TelegramBadRequest
    from tgbot.middlewares.errors import _is_harmless

    exc = TelegramBadRequest(
        method=None,
        message="Telegram server says - Bad Request: not enough rights "
                "to send text messages to the chat")
    assert _is_harmless(exc)


def test_bot_blocked_and_kicked_are_harmless():
    from aiogram.exceptions import TelegramBadRequest
    from tgbot.middlewares.errors import _is_harmless

    for text in ("Forbidden: bot was blocked by the user",
                 "Forbidden: bot was kicked from the supergroup chat",
                 "Bad Request: chat not found"):
        assert _is_harmless(TelegramBadRequest(method=None, message=text)), text


def test_real_bad_request_still_reported():
    """Настоящая ошибка 400 по-прежнему тревожит админа."""
    from aiogram.exceptions import TelegramBadRequest
    from tgbot.middlewares.errors import _is_harmless

    assert not _is_harmless(TelegramBadRequest(
        method=None, message="Bad Request: can't parse entities"))
