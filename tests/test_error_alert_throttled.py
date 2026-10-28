"""Одинаковые тревоги админу не чаще раза в час.

Ошибка в обработчике повторяется на каждом запросе. Без ограничения
админ получает сотню одинаковых сообщений: так и случилось 28.10.2026 —
в 21:56 пришли два «Ошибка в боте: TelegramBadRequest в base.py:120»
подряд от повторного нажатия «Завтра».

Заглушать надо по МЕСТУ ошибки, а не всё подряд: если сломается второе
место, о нём надо сообщить сразу.
"""
import datetime

import pytest

from tgbot.middlewares import errors


@pytest.fixture(autouse=True)
def _clean():
    errors._alerted.clear()
    yield
    errors._alerted.clear()


def test_first_always_alerts():
    assert errors._should_alert("user.py:843") is True


def test_repeat_suppressed():
    assert errors._should_alert("user.py:843") is True
    assert errors._should_alert("user.py:843") is False
    assert errors._should_alert("user.py:843") is False


def test_different_place_alerts_immediately():
    """Второе сломанное место — не повод молчать."""
    assert errors._should_alert("user.py:843") is True
    assert errors._should_alert("admin.py:120") is True


def test_alerts_again_after_cooldown():
    start = datetime.datetime(2026, 10, 28, 12, 0)
    assert errors._should_alert("user.py:843", now=start) is True
    assert errors._should_alert("user.py:843", now=start + datetime.timedelta(
        minutes=59)) is False
    assert errors._should_alert("user.py:843", now=start + datetime.timedelta(
        minutes=61)) is True


def test_cache_does_not_grow_forever():
    start = datetime.datetime(2026, 10, 28, 12, 0)
    for i in range(150):
        errors._should_alert(f"file{i}.py:1", now=start)
    assert len(errors._alerted) <= 101
    # Старые записи вычищены — новое место всё равно будит.
    assert errors._should_alert("fresh.py:1",
                                now=start + datetime.timedelta(hours=2)) is True
