"""«message is not modified» — не ошибка, а повторный тап.

Проверено на проде 28.10.2026: два таких трейсбека за 40 минут, оба из
`cb_tomorrow` → `_show_day` → `edit_text`. Человек нажал «Завтра», когда
карточка уже показывала завтрашний день (тап дважды, или зашли с конца
недели), Telegram ответил 400 «message is not modified».

Обработчик ошибок на это:
  * показывал пользователю алерт «Что-то пошло не так» на нормальном
    действии;
  * писал в лог ERROR с трейсбеком;
  * слал админу «Ошибка в боте».

Из 93 вызовов edit_text в проекте ни один не ловил этот случай — дыра
общая, поэтому чинится в обработчике ошибок, а не в каждом месте.
"""
import logging

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import EditMessageText
from aiogram.types import CallbackQuery, User

from tgbot.middlewares import errors


class _Cfg:
    class tg_bot:
        admin_ids = []


def _callback():
    """Настоящий CallbackQuery: on_error проверяет isinstance.

    Подкласс не годится (pydantic валидирует в `__init__`), а подменить
    `answer` на объекте нельзя — модель frozen. Патчим класс и смотрим,
    с какими аргументами его позвали.
    """
    return CallbackQuery(id="x", from_user=User(id=1, is_bot=False, first_name="a"),
                         chat_instance="c", data="d")


@pytest.fixture
def answered(monkeypatch):
    calls = []

    async def answer(self, text=None, show_alert=False, **kwargs):
        calls.append((text, show_alert))

    monkeypatch.setattr(CallbackQuery, "answer", answer)
    return calls


class _Update:
    def __init__(self, event):
        self.event = event


class _Event:
    def __init__(self, exception, event):
        self.exception = exception
        self.update = _Update(event)


class _Bot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text):
        self.sent.append((chat_id, text))


def _bad_request(text):
    return TelegramBadRequest(method=EditMessageText(chat_id=1, message_id=1, text="x"),
                              message=f"Telegram server says - Bad Request: {text}")


def test_detected_as_harmless():
    exc = _bad_request("message is not modified: specified new message content")
    assert errors._is_harmless(exc) is True


def test_other_bad_request_is_not_harmless():
    exc = _bad_request("message to edit not found")
    assert errors._is_harmless(exc) is False


def test_other_exceptions_are_not_harmless():
    assert errors._is_harmless(ValueError("message is not modified")) is False


@pytest.mark.asyncio
async def test_no_alert_no_admin_message(caplog, answered):
    cb = _callback()
    bot = _Bot()
    with caplog.at_level(logging.DEBUG):
        await errors.on_error(_Event(_bad_request("message is not modified"), cb),
                              bot, _Cfg())
    # Спиннер снят — кнопка ответила, но без текста.
    assert answered == [(None, False)], answered
    assert all(not alert for _, alert in answered), "алерт на нормальном действии"
    assert bot.sent == [], "админа потревожили зря"
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR], caplog.records


@pytest.mark.asyncio
async def test_real_error_still_alerts(caplog, answered):
    cb = _callback()
    bot = _Bot()
    with caplog.at_level(logging.DEBUG):
        await errors.on_error(_Event(ValueError("настоящая поломка"), cb), bot, _Cfg())
    assert answered == [(errors.TEXT_CALLBACK, True)]
    assert [r for r in caplog.records if r.levelno >= logging.ERROR]
