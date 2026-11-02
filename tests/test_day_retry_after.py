"""Лимит правок Telegram не роняет карточку дня.

В групповом чате несколько человек листают дни одной кнопкой. Telegram
отвечает 429 «Flood control exceeded on EditMessageText» с retry_after,
и это исключение доезжало до обработчика ошибок: человек видел «Что-то
пошло не так», админ получал тревогу.

Проверено на проде 02.11.2026: шесть таких ошибок за три часа, все из
_show_day (cb_today / cb_tomorrow), чат -1004366988460.

Теперь на 429 ждём retry_after и повторяем один раз.
"""
import datetime
from types import SimpleNamespace

import pytest
from aiogram.exceptions import TelegramRetryAfter
from aiogram.methods import EditMessageText

from tgbot.handlers import user as user_mod


class _Msg:
    def __init__(self, fail_times):
        self.calls = 0
        self.fail_times = fail_times

    async def edit_text(self, text, reply_markup=None):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise TelegramRetryAfter(
                method=EditMessageText(chat_id=1, message_id=1, text="x"),
                message="Flood control exceeded", retry_after=5)


class _Cb:
    def __init__(self, msg):
        self.message = msg
        self.answered = 0

    async def answer(self, *a, **k):
        self.answered += 1


@pytest.fixture
def no_sleep(monkeypatch):
    slept = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(user_mod.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(user_mod, "_day_text", _day_text)
    return slept


async def _day_text(repo, user, date):
    return "карточка"


@pytest.mark.asyncio
async def test_retry_after_waits_and_repeats(no_sleep):
    msg = _Msg(fail_times=1)
    cb = _Cb(msg)
    await user_mod._show_day(cb, None, SimpleNamespace(), datetime.date(2026, 11, 2))
    assert msg.calls == 2, "не повторили после 429"
    assert no_sleep == [5], no_sleep
    assert cb.answered == 1, "спиннер не сняли"


@pytest.mark.asyncio
async def test_retry_after_capped(no_sleep):
    """Не спим минуту: дольше десяти секунд ждать невежливо."""
    class _Long(_Msg):
        async def edit_text(self, text, reply_markup=None):
            self.calls += 1
            if self.calls == 1:
                raise TelegramRetryAfter(
                    method=EditMessageText(chat_id=1, message_id=1, text="x"),
                    message="Flood control exceeded", retry_after=600)
            return None

    msg = _Long(0)
    cb = _Cb(msg)
    await user_mod._show_day(cb, None, SimpleNamespace(), datetime.date(2026, 11, 2))
    assert no_sleep == [10], no_sleep


@pytest.mark.asyncio
async def test_normal_edit_untouched(no_sleep):
    msg = _Msg(fail_times=0)
    cb = _Cb(msg)
    await user_mod._show_day(cb, None, SimpleNamespace(), datetime.date(2026, 11, 2))
    assert msg.calls == 1
    assert no_sleep == []
