"""Адаптер: наша клавиатура -> InlineKeyboardMarkup.

Проверяем то, что важно на стыке: пустая клавиатура превращается в None
(иначе Telegram отвечает «reply markup is empty» и сообщение не уходит),
ссылки остаются ссылками, действия — действиями.
"""
from aiogram.types import InlineKeyboardMarkup

from core.keyboard import btn, kb
from tgbot.adapters.keyboard import to_inline_kb


def test_converts_rows_and_buttons():
    k = kb([btn("📅 Сегодня", "day:today"), btn("📅 Завтра", "day:tomorrow")],
           [btn("⚙️ Настройки", "settings")])
    out = to_inline_kb(k)
    assert isinstance(out, InlineKeyboardMarkup)
    assert len(out.inline_keyboard) == 2
    assert len(out.inline_keyboard[0]) == 2
    assert out.inline_keyboard[0][0].text == "📅 Сегодня"
    assert out.inline_keyboard[0][0].callback_data == "day:today"
    assert out.inline_keyboard[1][0].callback_data == "settings"


def test_empty_is_none():
    """None, а не пустой объект: на пустую клавиатуру Telegram ругается."""
    assert to_inline_kb(kb()) is None


def test_url_button_has_no_callback():
    out = to_inline_kb(kb([btn("📨 Поддержка", url="https://t.me/x")]))
    b = out.inline_keyboard[0][0]
    assert b.url == "https://t.me/x"
    assert b.callback_data is None


def test_all_actions_fit_telegram_limit():
    """Сквозная проверка: то, что прошло модель, влезает и в Telegram."""
    k = kb([btn("я" * 5, "я" * 32)])
    out = to_inline_kb(k)
    data = out.inline_keyboard[0][0].callback_data
    assert len(data.encode("utf-8")) <= 64
