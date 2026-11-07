"""Своя клавиатура: раскладка как данные, лимиты Telegram соблюдены.

Кнопка отваливается МОЛЧА: Telegram просто не нажимает то, что нарушает
его ограничения, и в логах ничего нет. Поэтому лимиты проверяются при
сборке, а не после жалобы студента.
"""
import pytest

from core.keyboard import (MAX_ACTION, MAX_BUTTONS, MAX_ROW, Button,
                           Keyboard, btn, kb)


def test_build_simple():
    k = kb([btn("📅 Сегодня", "day:today"), btn("📅 Завтра", "day:tomorrow")],
           [btn("⚙️ Настройки", "settings")])
    assert len(k.rows) == 2
    assert len(k.buttons) == 3
    assert k.buttons[0].text == "📅 Сегодня"
    assert k.buttons[0].action == "day:today"


def test_empty_keyboard_is_falsy():
    """Пустая клавиатура — это «без кнопок», а не «сломано»."""
    assert not Keyboard()
    assert not kb()


def test_url_button():
    b = btn("📨 Поддержка", url="https://t.me/x")
    assert b.url and not b.action


def test_url_and_action_together_rejected():
    """Нельзя и ссылку, и действие: платформа не поймёт, что делать."""
    with pytest.raises(ValueError, match="либо action, либо url"):
        Button(text="x", action="a", url="https://e.x")


def test_dead_button_rejected():
    """Кнопка без действия бесполезна — лучше упасть при сборке."""
    with pytest.raises(ValueError, match="некуда нажимать"):
        Button(text="x")


def test_action_byte_limit_cyrillic():
    """64 байта — предел Telegram. Кириллица занимает по 2 байта.

    33 кириллических символа = 66 байт: по символам влезло бы, по
    байтам нет. Проверяем именно байты.
    """
    ok = "я" * 32          # 64 байта ровно
    assert len(ok.encode()) == MAX_ACTION
    assert Button(text="x", action=ok).action == ok

    too_long = "я" * 33    # 66 байт
    with pytest.raises(ValueError, match="предел 64"):
        Button(text="x", action=too_long)


def test_row_limit():
    """12 кнопок в ряду — предел Telegram."""
    assert len(kb([btn(f"b{i}", f"a{i}") for i in range(MAX_ROW)]).rows[0]) == MAX_ROW
    with pytest.raises(ValueError, match="предел 12"):
        kb([btn(f"b{i}", f"a{i}") for i in range(MAX_ROW + 1)])


def test_total_limit():
    """100 кнопок всего."""
    rows = [[btn(f"b{i}{j}", f"a{i}{j}") for j in range(10)] for i in range(10)]
    assert len(kb(*rows).buttons) == MAX_BUTTONS
    with pytest.raises(ValueError, match="предел 100"):
        kb(*(rows + [[btn("лишняя", "x")]]))


def test_frozen():
    """Клавиатура не должна меняться на ходу: экраны собираются заново."""
    k = kb([btn("a", "x")])
    with pytest.raises(Exception):
        k.rows = ()
