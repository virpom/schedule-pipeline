"""Превращение нашей клавиатуры в телеграмную.

Единственное место, где клавиатура из ядра встречается с aiogram.
Адаптер MAX будет выглядеть так же и лежать рядом.
"""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from core.keyboard import Keyboard


def to_inline_kb(keyboard: Keyboard) -> InlineKeyboardMarkup | None:
    """Собрать ``InlineKeyboardMarkup`` или None для пустой клавиатуры.

    None, а не пустой объект: Telegram на пустую клавиатуру отвечает
    ошибкой «reply markup is empty», и сообщение не уходит вовсе.
    """
    if not keyboard:
        return None
    rows = []
    for row in keyboard.rows:
        out = []
        for b in row:
            if b.url:
                out.append(InlineKeyboardButton(text=b.text, url=b.url))
            else:
                out.append(InlineKeyboardButton(text=b.text,
                                                callback_data=b.action))
        rows.append(out)
    return InlineKeyboardMarkup(inline_keyboard=rows)
