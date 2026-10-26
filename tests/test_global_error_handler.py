"""Глобальный обработчик ошибок: пользователь получает ответ, а не тишину.

План 022. Без обработчика исключение в хендлере aiogram писалось в лог и
на этом всё: `cb.answer()` не вызывался, спиннер на кнопке висел до
таймаута, обычное сообщение оставалось без ответа.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.types import CallbackQuery, Chat, ErrorEvent, Message, Update, User

from tgbot.middlewares.errors import TEXT_CALLBACK, TEXT_MESSAGE, _place, on_error


def _bot():
    return AsyncMock()


def _config(admins=(555,)):
    cfg = MagicMock()
    cfg.tg_bot.admin_ids = list(admins)
    return cfg


def _cb(bot):
    """CallbackQuery, смонтированный на бота — иначе answer() бросит."""
    return CallbackQuery(
        id="1", from_user=User(id=1, is_bot=False, first_name="T"),
        chat_instance="x", data="ed:bday:99",
    ).as_(bot)


def _msg(bot):
    return Message(
        message_id=1, date=0, chat=Chat(id=1, type="private"),
        from_user=User(id=1, is_bot=False, first_name="T"), text="привет",
    ).as_(bot)


def _error(exc):
    return exc


async def test_callback_gets_answer_instead_of_spinner():
    """Главное: подделанный callback_data не оставляет кнопку висеть.

    `ed:bday:99` — реальный путь: int() проходит, а WEEKDAY_FULL[98]
    падает с IndexError. Раньше пользователь не получал ничего.
    """
    bot = _bot()
    cb = _cb(bot)
    err = IndexError("list index out of range")
    ev = ErrorEvent(update=Update(update_id=1, callback_query=cb), exception=err)

    await on_error(ev, bot, _config())

    bot.assert_awaited(), "answer() не был вызван"
    sent = [c.args[0] for c in bot.await_args_list if c.args]
    assert any(getattr(a, "text", None) == TEXT_CALLBACK for a in sent), sent
    # show_alert, иначе человек не поймёт, почему ничего не открылось.
    assert any(getattr(a, "show_alert", False) is True for a in sent)


async def test_message_gets_answer():
    """Сообщение тоже не должно оставаться без ответа."""
    bot = _bot()
    msg = _msg(bot)
    ev = ErrorEvent(update=Update(update_id=2, message=msg),
                    exception=ValueError("boom"))

    await on_error(ev, bot, _config())

    sent = [c.args[0] for c in bot.await_args_list if c.args]
    assert any(getattr(a, "text", None) == TEXT_MESSAGE for a in sent), sent


async def test_admin_notified_without_traceback():
    """Админу уходит тип и место, но не traceback.

    В тексте исключений бывают токены и данные пользователей — в
    Telegram их слать нельзя.
    """
    bot = _bot()
    cb = _cb(bot)
    ev = ErrorEvent(update=Update(update_id=3, callback_query=cb),
                    exception=KeyError("секрет-токен-123"))

    await on_error(ev, bot, _config(admins=(555, 777)))

    admin_msgs = [c.args[1] for c in bot.send_message.await_args_list]
    assert len(admin_msgs) == 2, admin_msgs
    assert all("KeyError" in m for m in admin_msgs)
    assert not any("секрет-токен-123" in m for m in admin_msgs), admin_msgs


async def test_blocked_admin_does_not_break_handler():
    """Админ заблокировал бота — обработчик не должен падать.

    Иначе ошибка в уведомлении админа съест ответ пользователю.
    """
    bot = AsyncMock()
    bot.side_effect = [None, Exception("bot was blocked by the user")]
    cb = _cb(bot)
    ev = ErrorEvent(update=Update(update_id=4, callback_query=cb),
                    exception=RuntimeError("x"))

    await on_error(ev, bot, _config(admins=(555, 777)))  # не бросает


async def test_answer_failure_does_not_break_handler():
    """Сообщение удалено — answer падает, обработчик выживает."""
    bot = _bot()
    bot.side_effect = Exception("message to answer not found")
    cb = _cb(bot)
    ev = ErrorEvent(update=Update(update_id=5, callback_query=cb),
                    exception=RuntimeError("x"))

    await on_error(ev, bot, _config())  # не бросает


def test_place_points_at_last_frame():
    """Без места «TypeError» админу бесполезен."""
    def inner():
        raise KeyError("x")

    try:
        inner()
    except KeyError as exc:
        place = _place(exc)

    assert place.startswith("test_global_error_handler.py:"), place
    assert place.rsplit(":", 1)[1].isdigit()


def test_place_without_traceback():
    assert _place(ValueError("нет трейсбека")) == "?"


async def test_without_handler_user_gets_nothing():
    """Доказательство дефекта: без регистрации ответа нет вовсе.

    Не проверка кода, а проверка утверждения плана — иначе тест выше
    доказывал бы только, что функция работает, но не что она нужна.
    """
    from aiogram import Dispatcher
    from aiogram.fsm.storage.memory import MemoryStorage

    async def answers(register: bool) -> int:
        bot = _bot()
        dp = Dispatcher(storage=MemoryStorage(), config=_config())
        if register:
            dp.errors.register(on_error)

        @dp.callback_query()
        async def boom(cb):
            raise IndexError("list index out of range")

        cb = CallbackQuery(
            id="1", from_user=User(id=1, is_bot=False, first_name="T"),
            chat_instance="x", data="ed:bday:99",
        ).as_(bot)
        try:
            await dp.feed_update(bot, Update(update_id=1, callback_query=cb))
        except Exception:
            pass
        return len(bot.await_args_list)

    assert await answers(register=False) == 0, "без обработчика ответ уже был?"
    assert await answers(register=True) == 1, "обработчик не ответил"
