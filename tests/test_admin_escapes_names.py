"""Имена из Telegram экранируются в админских экранах.

`full_name` и `username` приходят от Telegram без фильтра: человек может
назваться «<b>Вася</b>», «&lt;» или «a & b». Бот отвечает с
parse_mode=HTML, поэтому такое имя либо рисует чужую разметку, либо
ломает сообщение целиком — Telegram отвечает «can't parse entities»,
и экран не открывается.

На проде уже есть пользователь с именем «7>10» (символ «>» сам по себе
безопасен, но показывает, что фильтра нет).
"""
import inspect

from tgbot.handlers import admin as admin_mod


def test_user_line_escapes():
    body = inspect.getsource(admin_mod._user_line)
    assert "escape(" in body, "имя не экранируется"
    assert "escape(u.full_name" in body or "escape(u.full_name or" in body


def test_teachers_text_escapes():
    body = inspect.getsource(admin_mod._teachers_text)
    assert "escape(" in body, "фамилия преподавателя не экранируется"


def test_button_labels_not_escaped():
    """В тексте кнопки HTML не парсится — там escape испортил бы вид.

    Проверяем обратное: подпись кнопки остаётся сырой, иначе админ
    увидел бы «&lt;» вместо «<».
    """
    body = inspect.getsource(admin_mod._user_option)
    assert "escape(" not in body


def test_escape_actually_needed():
    """Демонстрация: без escape строка ломает HTML-разметку."""
    from html import escape
    name = "<b>Вася</b> & Ко"
    raw = f"@nick — {name}"
    safe = f"@nick — {escape(name)}"
    assert "<b>" in raw
    assert "<b>" not in safe and "&lt;b&gt;" in safe
