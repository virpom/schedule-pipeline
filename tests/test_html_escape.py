"""Текст с сайта и из редактора не ломает разметку (план 064).

Бот шлёт всё с parse_mode=HTML. Один `<` в предмете — и Telegram
отвечает BadRequest, а экран дня не открывается ни у кого в группе,
включая старосту, который его ввёл.

Экранирование стоит на выводе, а не на записи, вопреки рекомендации
плана: поиск по предмету и преподавателю идёт через LIKE
(`college_lesson.py`), и «&lt;» в базе сломал бы его. План сам
признал это в разделе «Риски», но всё равно советовал писать
экранированное.
"""
import datetime
import inspect
import types

import pytest

from common.schedule import empty_day, format_day, _esc


def _lesson(**kw):
    base = dict(para=1, para_end=1, subject="Математика", teacher="Иванов И.И.",
                room="101", group="ДП-26", changed=False, action="", time_note="")
    base.update(kw)
    return types.SimpleNamespace(**base)


def _fmt(lesson, **kw):
    return format_day(datetime.date(2026, 10, 28), [lesson], {}, {}, **kw)


def test_esc_basics():
    assert _esc("Математика < 5") == "Математика &lt; 5"
    assert _esc("Физика & Химия") == "Физика &amp; Химия"
    assert _esc("") == ""
    assert _esc(None) == ""


def test_subject_with_less_than():
    out = _fmt(_lesson(subject="Математика < 5"))
    assert "&lt; 5" in out
    assert "Математика < 5" not in out


def test_subject_with_ampersand():
    assert "&amp;" in _fmt(_lesson(subject="Физика & Химия"))


def test_subject_with_tag_not_rendered():
    """Валидный тег в предмете не должен становиться разметкой."""
    out = _fmt(_lesson(subject="<b>Физика</b>"))
    assert "&lt;b&gt;Физика&lt;/b&gt;" in out


def test_teacher_and_room_escaped():
    out = _fmt(_lesson(teacher="Иванов <И.И.>", room="ауд. <101>"))
    assert "Иванов &lt;И.И.&gt;" in out
    assert "&lt;101&gt;" in out


def test_cancelled_line_escaped():
    out = _fmt(_lesson(subject="Химия < 2", action="cancel"))
    assert "&lt; 2" in out


def test_empty_day_note_escaped():
    d = datetime.date(2026, 10, 28)
    out = empty_day(d, "Занятий нет. Смотреть <тут>")
    assert "&lt;тут&gt;" in out
    assert "<тут>" not in out


def test_editor_texts_escaped():
    from tgbot.handlers import editor
    for fn in (editor.base_day_text, editor.sub_day_text):
        assert "escape(" in inspect.getsource(fn), f"{fn.__name__} не экранирует"


def test_bell_text_escaped():
    from tgbot.services import bell
    assert "escape(" in inspect.getsource(bell._tick)


def test_search_not_broken_by_escaping():
    """Данные в базе остаются сырыми — поиск по LIKE работает."""
    from infrastructure.database.repo import college_lesson as mod
    src = inspect.getsource(mod)
    assert "escape" not in src, "экранирование попало в слой записи"


@pytest.mark.parametrize("field,limit", [("subject", 256), ("teacher", 128), ("room", 64)])
def test_length_limit(field, limit):
    from tgbot.handlers import editor
    assert editor._MAX_FIELD[{"subject": "предмет", "teacher": "преподаватель",
                              "room": "кабинет"}[field]] == limit
    assert editor._too_long("я" * limit, {"subject": "предмет", "teacher": "преподаватель",
                                          "room": "кабинет"}[field]) is None
    assert editor._too_long("я" * (limit + 1), {"subject": "предмет", "teacher": "преподаватель",
                                                "room": "кабинет"}[field]) is not None


@pytest.mark.parametrize("fn", ["on_subject", "on_teacher", "on_room"])
def test_handlers_check_length(fn):
    from tgbot.handlers import editor
    assert "_too_long" in inspect.getsource(getattr(editor, fn))
