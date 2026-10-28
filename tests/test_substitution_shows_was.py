"""Замена показывает, что стояло раньше (план 103).

Листок замен устроен как «было → стало». Парсер читал обе колонки, но в
базу шла только «стало»: `was` выбрасывался, а поле comment заполнялось
строкой raw_now (вторая копия того же «стало») и нигде не выводилось.

При смене преподавателя это главный вопрос студента: «ИГ – Иванова Н.А. 🔄»
без строки «было» не отвечает, что было раньше.

На проде 28.10: 48 колледжных замен, у всех comment был непустой и все
48 — «стало».
"""
import datetime

from common.schedule import DETAIL_BRIEF, DETAIL_FULL, format_day
from infrastructure.database.models import BellSchedule
from tgbot.services.schedule_layer import Slot

MONDAY = datetime.date(2026, 10, 26)


def _bell():
    return {("MONDAY", "I_IV", 4): BellSchedule(
        day_type="MONDAY", course_group="I_IV", para=4,
        start=datetime.time(15, 0), h1_end=datetime.time(15, 45),
        h2_start=datetime.time(15, 55), end=datetime.time(16, 40))}


def _slot(**kw):
    base = dict(para=4, subject="Биология", teacher="Утева О.В.",
                room="202", changed=True, action="replace", group="ТЭк-26")
    base.update(kw)
    return Slot(**base)


def test_was_shown_in_full_detail():
    text = format_day(MONDAY, [_slot(comment="Обществознание – Кекеева К.А.")],
                      _bell(), {}, detail=DETAIL_FULL)
    assert "было" in text.lower(), text
    assert "Кекеева" in text, text


def test_was_hidden_in_brief():
    """Короткая выдача не должна раздуваться."""
    text = format_day(MONDAY, [_slot(comment="Обществознание – Кекеева К.А.")],
                      _bell(), {}, detail=DETAIL_BRIEF)
    assert "было" not in text.lower(), text


def test_no_was_for_added_lesson():
    text = format_day(MONDAY, [_slot(action="add", comment="")],
                      _bell(), {}, detail=DETAIL_FULL)
    assert "было" not in text.lower(), text


def test_was_not_shown_for_unchanged():
    text = format_day(MONDAY, [_slot(changed=False, comment="Старое")],
                      _bell(), {}, detail=DETAIL_FULL)
    assert "было" not in text.lower(), text


def test_was_is_escaped():
    text = format_day(MONDAY, [_slot(comment="<b>ЖП</b> & Ко")],
                      _bell(), {}, detail=DETAIL_FULL)
    assert "<b>ЖП</b>" not in text
    assert "&lt;b&gt;" in text
