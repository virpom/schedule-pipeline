"""Уведомление о правке показывает время пар.

План 040. Уведомление приходит пушем заранее, когда студент не в боте
и не помнит сетку. Раньше в нём был только номер пары и предмет — по
номеру время не восстановить: п2 это 10:45–12:40 на I_IV и 10:45–12:20
на II_III, а понедельник отличается от остальных дней на всех парах.

Теперь тело уведомления собирает `format_day` — ровно то, что студент
видит на экране «Сегодня». Третья реализация форматирования дня убрана.
"""
import datetime
import inspect

from common.schedule import format_day
from tgbot.services import notify_edits


def _code(module) -> str:
    src = inspect.getsource(module)
    return "\n".join(line.split("#", 1)[0] for line in src.splitlines())


def test_notify_uses_format_day():
    """Свой форматтер убран, взят общий."""
    code = _code(notify_edits)
    assert "format_day(" in code, "уведомление снова форматирует день само"
    assert "_slots_text" not in code, "вернулась третья реализация"


def test_slots_text_removed():
    assert not hasattr(notify_edits, "_slots_text")


def test_fmt_day_removed():
    """Свой заголовок дня тоже не нужен — format_day его пишет."""
    assert not hasattr(notify_edits, "_fmt_day")


def test_no_duplicate_header():
    """format_day сам пишет «📅 Вторник, 27 октября» — второго быть не должно."""
    code = _code(notify_edits)
    assert "📅" not in code, "свой заголовок дня остался и задублируется"


def test_group_named_in_body():
    """Группа названа, иначе в чате непонятно, о ком речь."""
    code = _code(notify_edits)
    assert "группа <b>" in code


class _BS:
    """Звонок второй пары: 10:45–11:20 / 11:25–12:05."""

    def __init__(self):
        self.start = datetime.time(10, 45)
        self.h1_end = datetime.time(11, 20)
        self.h2_start = datetime.time(11, 25)
        self.end = datetime.time(12, 5)


class _Slot:
    def __init__(self, para, subject):
        self.para = para
        self.para_end = para
        self.subject = subject
        self.teacher = ""
        self.room = ""
        self.changed = False
        self.action = ""
        self.group = "ДП-26"
        self.time_note = ""


def test_rendered_notification_contains_time():
    """Сквозная проверка: время в тексте есть."""
    date = datetime.date(2026, 10, 27)  # вторник
    bell = {("OTHER", "I_IV", 2): _BS()}
    text = format_day(date, [_Slot(2, "Деловая культура")], bell, {},
                      "brief", meta="group", show_rov=False)
    assert "10:45" in text, text
    assert "Деловая культура" in text


def test_rendered_notification_contains_day():
    """День тоже назван — иначе непонятно, на какую дату правка."""
    date = datetime.date(2026, 10, 27)
    text = format_day(date, [_Slot(2, "Деловая культура")], {}, {},
                      "brief", meta="group", show_rov=False)
    assert "27" in text and "октября" in text.lower()
