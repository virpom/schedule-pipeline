"""Редактор и настройки: правки, которые молча терялись или ломали меню.

Три дефекта:

* план 145 — «Пропустить» на шаге кабинета у базовой пары вызывал
  `_save_sub`, а у базы нет даты: `KeyError: 'date'`, правка терялась
  без ошибки и без подтверждения;
* план 162 — ссылка поддержки сохранялась без проверки, а Telegram
  отклоняет сообщение целиком на недопустимый url, то есть ломается
  главное меню у всех;
* та же дыра с часовым поясом в парсере настроек, что и в /setnight.
"""
import inspect

import pytest

from tgbot.handlers.admin import _night, _url
from tgbot.handlers import editor


def test_teacher_step_picks_callback_by_layer():
    """`on_teacher` выбирает колбэк по слою, как `on_subject`.

    Раньше всегда стоял ed:sub_skip_room. У базовой правки даты нет,
    и _save_sub падал с KeyError: 'date'.
    """
    src = inspect.getsource(editor.on_teacher)
    assert 'data.get("layer") == "sub"' in src, (
        "колбэк не различает слой — план 145"
    )
    assert "ed:skip_room" in src, "нет ветки для базовой пары"
    assert "ed:sub_skip_room" in src, "нет ветки для замены"


def test_skip_room_base_goes_to_save_base():
    """`ed:skip_room` ведёт в `_save_base`, `ed:sub_skip_room` — в `_save_sub`."""
    base_src = inspect.getsource(editor.cb_skip_room)
    sub_src = inspect.getsource(editor.cb_sub_skip_room)
    assert "_save_base" in base_src
    assert "_save_sub" in sub_src
    # И наоборот — чтобы ветки не перепутались.
    assert "_save_sub" not in base_src
    assert "_save_base" not in sub_src


def test_save_sub_requires_date():
    """`_save_sub` читает дату первой строкой — значит у базы её нет.

    Это и есть корень KeyError: подтверждаем контракт, а не поведение.
    """
    src = inspect.getsource(editor._save_sub)
    assert 'data["date"]' in src


def test_url_accepts_telegram_schemes():
    assert _url("https://t.me/+abc") == ("https://t.me/+abc",)
    assert _url("http://example.ru") == ("http://example.ru",)
    assert _url("tg://resolve?domain=x") == ("tg://resolve?domain=x",)
    assert _url("") == ("",), "пустая строка должна убирать кнопку"


def test_url_rejects_everything_else():
    """Telegram отклоняет сообщение целиком — значит не пускать в БД.

    Проверял на живом Bot API: url принимает только http, https и tg.
    """
    for bad in ("abc", "ftp://x", "javascript:alert(1)", "www.x.ru",
                "t.me/x", "https://"):
        with pytest.raises(ValueError):
            _url(bad)


def test_url_whitespace_only_clears_button():
    """Одни пробелы — это «убрать кнопку», а не ошибка.

    strip() превращает их в пустую строку, а пустая строка допустима.
    """
    assert _url("  ") == ("",)


def test_url_strips_whitespace():
    """Пробелы вокруг ссылки не должны ломать кнопку."""
    assert _url("  https://t.me/x  ") == ("https://t.me/x",)


def test_settings_support_uses_url_parser():
    """В SETTINGS у support стоит _url, а не пропускающий lambda."""
    from tgbot.handlers.admin import SETTINGS

    assert SETTINGS["support"].parse is _url


def test_night_setting_rejects_aware_time():
    """Тот же дефект, что в /setnight, но через экран настроек.

    «23:00+03:00» даёт aware-время, _in_night падает с TypeError,
    поллер ловит его общим except и перестаёт опрашивать сайт.
    """
    assert _night("23:00 07:00") == ("23:00", "07:00")
    for bad in ("23:00+03:00 07:00", "23 07", "07:00:00 23:00",
                "23:00", "23:00 07:00 08:00", ""):
        with pytest.raises(ValueError):
            _night(bad)
