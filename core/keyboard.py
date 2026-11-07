"""Клавиатура как данные, без привязки к платформе.

Зачем своя модель, а не ``InlineKeyboardMarkup``: она нужна, чтобы
логика экранов не знала про Telegram. Telegram и MAX по-разному
называют одно и то же — у первого ``callback_data`` (строка до 64
байт), у второго ``payload`` в объекте кнопки, — но раскладка кнопок
по рядам у них общая. Раскладку и держим здесь.

Адаптеры (``tgbot/adapters/keyboard.py``) превращают это в клавиатуру
конкретной платформы. Ядро про них не знает.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Ограничения Telegram, из-за которых кнопка отваливается МОЛЧА.
# Проверяются в тестах и в адаптере: лучше упасть при сборке экрана,
# чем отдать клавиатуру, где половина кнопок не нажимается.
MAX_ROW = 12          # кнопок в ряду
MAX_BUTTONS = 100     # всего в клавиатуре
MAX_ACTION = 64       # байт в callback_data


@dataclass(frozen=True)
class Button:
    """Одна кнопка.

    ``action`` — то, что платформа вернёт боту при нажатии: у Telegram
    это ``callback_data``, у MAX — payload. Одна строка, одна и та же
    на обеих платформах, поэтому сценарии не переписываются.

    ``url`` — кнопка-ссылка: нажатие не приходит боту вообще, поэтому
    ``action`` у неё пустой.
    """

    text: str
    action: str = ""
    url: str = ""

    def __post_init__(self) -> None:
        if self.url and self.action:
            raise ValueError(
                f"кнопка «{self.text}»: либо action, либо url, не оба")
        if not self.url and not self.action:
            raise ValueError(f"кнопка «{self.text}»: некуда нажимать")
        if self.action:
            size = len(self.action.encode("utf-8"))
            if size > MAX_ACTION:
                # 64 байта — предел Telegram. Кириллица в UTF-8 занимает
                # два байта на символ, поэтому проверяем именно байты.
                raise ValueError(
                    f"action «{self.action}» — {size} байт, предел {MAX_ACTION}")


@dataclass(frozen=True)
class Keyboard:
    """Ряды кнопок. Пустая клавиатура допустима: сообщение без кнопок."""

    rows: tuple[tuple[Button, ...], ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        total = sum(len(row) for row in self.rows)
        if total > MAX_BUTTONS:
            raise ValueError(f"кнопок {total}, предел {MAX_BUTTONS}")
        for i, row in enumerate(self.rows):
            if len(row) > MAX_ROW:
                raise ValueError(
                    f"ряд {i}: кнопок {len(row)}, предел {MAX_ROW}")

    def __bool__(self) -> bool:
        return bool(self.rows)

    @property
    def buttons(self) -> list[Button]:
        return [b for row in self.rows for b in row]


def kb(*rows: list[Button]) -> Keyboard:
    """Собрать клавиатуру: ``kb([b1, b2], [b3])``."""
    return Keyboard(rows=tuple(tuple(r) for r in rows))


def btn(text: str, action: str = "", url: str = "") -> Button:
    return Button(text=text, action=action, url=url)
