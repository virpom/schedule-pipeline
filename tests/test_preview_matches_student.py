"""Превью показывает то же, что студент (план 065).

Три расхождения:
1. detail был зашит в "full", а 202 из 255 студентов на проде видят
   brief — староста проверял экран, которого нет ни у кого;
2. превью строилось из слоёв (get_day_slots), а студент читает
   college_lesson. Если _rebuild упал, превью показывало правильные
   данные, а студент — старые;
3. три дня вместо семи — правку базы не проверить на следующей неделе,
   хотя она меняет все дни окна.
"""
import datetime
import inspect

from common.schedule import DETAIL_BRIEF, DETAIL_FULL
from tgbot.handlers import editor


def _src(fn) -> str:
    return inspect.getsource(fn)


def test_detail_default_is_brief():
    """По умолчанию — то, что видит большинство."""
    sig = inspect.signature(editor.preview_text)
    assert sig.parameters["detail"].default == DETAIL_BRIEF


def test_detail_not_hardcoded_full():
    body = _src(editor.preview_text)
    assert 'detail="full"' not in body, "detail по-прежнему зашит"
    assert "detail=detail" in body


def test_detail_comes_from_user():
    """cb_preview_day передаёт настройку старосты."""
    assert "user.bell_detail" in _src(editor.cb_preview_day)
    assert "user" in inspect.signature(editor.cb_preview_day).parameters


def test_reads_college_lesson():
    """Источник — та же таблица, что читает студент."""
    body = _src(editor.cb_preview_day)
    assert "get_for_group_date" in body, "превью строится из слоёв"
    assert "get_day_slots" not in body


def test_seven_days():
    body = _src(editor.cb_preview)
    assert "range(0, 7)" in body, "превью по-прежнему на три дня"


def test_seven_buttons_two_per_row():
    """Семь кнопок в столбик — многовато."""
    body = _src(editor.cb_preview)
    assert "buttons[i:i + 2]" in body or "i:i + 2" in body


def test_preview_keeps_time_and_pairing():
    """time_note и para_end передаются: иначе время пары разойдётся."""
    body = _src(editor.cb_preview_day)
    assert "time_note" in body
    assert "para_end" in body


def test_all_slot_fields_forwarded():
    """preview_text не теряет поля Slot."""
    body = _src(editor.preview_text)
    for field in ("changed", "action", "comment"):
        assert field in body, f"{field} не передаётся"


def test_both_details_render_differently():
    """brief и full дают разный текст — иначе переключатель бессмысленен."""
    from tgbot.services.schedule_layer import Slot

    slots = [Slot(1, "Математика", "Иванов И.И.", "204", changed=True)]
    class _BS:
        start = datetime.time(9, 0)
        end = datetime.time(10, 35)
        h1_end = datetime.time(9, 45)
        h2_start = datetime.time(9, 55)

    bell = {("MONDAY", "I_IV", 1): _BS()}   # 9 ноября 2026 — понедельник
    d = datetime.date(2026, 11, 9)
    brief = editor.preview_text("ДП-26", d, slots, bell, {}, detail=DETAIL_BRIEF)
    full = editor.preview_text("ДП-26", d, slots, bell, {}, detail=DETAIL_FULL)
    assert brief != full, "detail не влияет на текст"
    assert "09:00" in full
