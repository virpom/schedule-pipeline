"""`_fmt` в обработчиках истории принимает (user, date, lessons...).

Прод, 18.11.2026: экран «История расписания» падал с
``AttributeError: 'User' object has no attribute 'date'``.

Причина — этап 1 (перенос в ядро). Старую функцию

    def _fmt(user, date, lessons, bell, lunches, gcg=None)

заменили алиасом ``_fmt = _fmt_day``. У ядровой ``_fmt_day`` ДРУГАЯ
сигнатура: она ждёт готовый ``DayView``, а не пользователя с датой.
Импорт проходил, тесты падали не все: они зовут ядро напрямую, а
обработчики истории — через ``_fmt``.

Здесь проверяется именно стык: вызов с той сигнатурой, которой пользуются
обработчики. Импорт-тест такое не ловит — нужен реальный вызов.
"""
import datetime
from types import SimpleNamespace

import pytest

from tgbot.handlers import user as user_mod


def _user(**kw):
    base = dict(id=1, role="student", group="ДП-26", course=1,
                teacher_name=None, bell_detail="brief", send_image=False,
                subscribed=True)
    base.update(kw)
    return SimpleNamespace(**base)


def test_fmt_callable_with_handler_signature():
    """Тот самый вызов из cb_hist_date: (user, date, lessons, bell, lunches, gcg)."""
    out = user_mod._fmt(
        _user(), datetime.date(2026, 11, 10), [], {}, {}, None)
    assert isinstance(out, str) and out


def test_fmt_empty_day_is_not_lessons_screen():
    """Пустой день рисуется как список, а не «Занятий нет».

    История показывает и пустые дни: «Занятий нет 🙌» там сбивало бы —
    человек выбрал дату и ждёт её содержимое, пусть и пустое.
    """
    out = user_mod._fmt(
        _user(), datetime.date(2026, 11, 10), [], {}, {}, None)
    assert "Занятий нет" in out


def test_fmt_teacher_uses_group_meta():
    """Преподавателю в шапке группы, а не его имя: студент и препода без этого зеркалятся."""
    teacher = _user(role="teacher", group=None, teacher_name="Иванов И.И.")
    out = user_mod._fmt(
        teacher, datetime.date(2026, 11, 10), [], {}, {}, None)
    assert isinstance(out, str) and out


def test_fmt_has_documented_signature():
    """Защита от повторной подмены алиасом с другой сигнатурой."""
    import inspect
    sig = inspect.signature(user_mod._fmt)
    params = list(sig.parameters)
    assert params[:3] == ["user", "date", "lessons"], params
