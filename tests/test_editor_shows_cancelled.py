"""Редактор показывает, что пара отменена (план 094).

sub_day_text собирает список пар сам, без format_day, и смотрел только
s.changed. get_day_slots для отменённой пары ставит changed=True И
action=SUB_CANCEL — первого хватало, чтобы попасть в ветку «замена»,
второй терялся.

Староста ставил отмену, возвращался на экран дня и видел обычную пару
со значком 🔄 — то есть проверить свою же правку не мог. Студент при
этом видел «❌ отменено».
"""
import datetime

from common.schedule import SUB_CANCEL
from tgbot.handlers.editor import sub_day_text
from tgbot.services.schedule_layer import Slot

D = datetime.date(2026, 11, 9)


def _text(slots):
    return sub_day_text("ДП-26", D, slots)


def test_cancelled_marked():
    got = _text([Slot(1, "Математика", "Иванов И.И.", "101",
                      changed=True, action=SUB_CANCEL)])
    assert "отменено" in got, got


def test_cancelled_not_shown_as_plain_change():
    got = _text([Slot(1, "Математика", "Иванов И.И.", "101",
                      changed=True, action=SUB_CANCEL)])
    assert "🔄" not in got, f"отмена показана как замена:\n{got}"


def test_replacement_still_shows_flag():
    got = _text([Slot(1, "Право", "Петров П.П.", "102",
                      changed=True, action="replace")])
    assert "🔄" in got, got
    assert "отменено" not in got, got


def test_plain_pair_no_flag():
    got = _text([Slot(1, "Химия", "Сидоров С.С.", "103")])
    assert "🔄" not in got and "отменено" not in got, got


def test_empty_day():
    assert "Пар нет" in _text([])
