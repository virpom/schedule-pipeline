"""Экраны редактора в ядре: та же раскладка и те же тексты.

Перенос редактора (этап 1, план 173) опасен тем, что кнопка действия
перестанет нести `weeks` — и староста начнёт править не ту строку
вузовского расписания, где на один слот несколько недель.

Проверено на 27 экранах: 0 расхождений с прежним видом.
"""
import datetime

from core.editor import (base_day_text, paras_kb, slot_actions_kb,
                         sub_day_text, sub_slots_kb)
from core.schedule_layer import Slot


def _slots():
    return [
        Slot(1, "Математика", "Иванов И.И.", "101", group="ДП-26"),
        Slot(2, "Физика", "Петров П.П.", "202", group="ДП-26",
             changed=True, action="replace"),
        Slot(3, "Химия", "Сидоров С.С.", "", group="ДП-26", weeks="ODD"),
    ]


def test_action_button_carries_weeks():
    """Без weeks upsert создаёт дубль, а delete не находит строку."""
    k = slot_actions_kb(1, "ANY", 2, True, weeks="5,6,7,8")
    actions = [b.action for b in k.buttons]
    assert "ed:edit:1:ANY:2:5,6,7,8" in actions
    assert "ed:del:1:ANY:2:5,6,7,8" in actions


def test_action_button_without_weeks_uses_underscore():
    k = slot_actions_kb(1, "ANY", 2, True)
    assert "ed:edit:1:ANY:2:_" in [b.action for b in k.buttons]


def test_delete_button_only_when_value():
    """Убирать можно только то, что есть."""
    with_value = [b.text for b in slot_actions_kb(1, "ANY", 1, True).buttons]
    empty = [b.text for b in slot_actions_kb(1, "ANY", 1, False).buttons]
    assert any("Убрать" in t for t in with_value)
    assert not any("Убрать" in t for t in empty)


def test_paras_kb_marks_multiple_week_rows():
    """У вуза на слот несколько строк — кнопка говорит, сколько."""
    slots = [Slot(3, "Компьютерное моделирование", "И", "1",
                  weeks="5,6,7,8"),
             Slot(3, "Компьютерное моделирование", "И", "1",
                  weeks="9,10,11,12,13")]
    k = paras_kb(1, "ANY", slots)
    labels = [b.text for b in k.buttons]
    assert any("+1" in t for t in labels), labels


def test_paras_kb_marks_changed():
    k = paras_kb(1, "ANY", _slots())
    labels = [b.text for b in k.buttons]
    assert any("🔄" in t for t in labels)


def test_base_day_text_groups_vuz_weeks():
    """Четыре строки одной пары печатались четыре раза подряд (план 153).

    Теперь одна строка на пару, варианты через «·» с неделями.
    """
    slots = [Slot(3, "Моделирование", "И", "1", weeks="5,6"),
             Slot(3, "Моделирование", "И", "1", weeks="7,8")]
    text = base_day_text("ГИ-23", 1, "ANY", slots)
    assert text.count("Моделирование") == 2, text
    assert "(5,6)" in text and "(7,8)" in text


def test_base_day_text_empty():
    assert "Пар нет" in base_day_text("ДП-26", 1, "ANY", [])


def test_sub_day_text_shows_cancel():
    """Отменённая пара помечается «отменено», а не обычным 🔄.

    get_day_slots ставит отменённой паре оба признака, и староста видел
    🔄 — проверить свою же правку было нельзя.
    """
    slots = [Slot(1, "Математика", "И", "1", changed=True, action="cancel")]
    text = sub_day_text("ДП-26", datetime.date(2026, 11, 10), slots)
    assert "отменено" in text
    assert "🔄" not in text


def test_sub_slots_kb_labels():
    slots = _slots()
    subs = {2: Slot(2, "Физкультура", "П", "спортзал", action="replace"),
            3: Slot(3, "", "", "", action="cancel")}
    k = sub_slots_kb("2026-11-10", slots, subs)
    labels = [b.text for b in k.buttons]
    assert any("🔄 Физкультура" in t for t in labels), labels
    assert any("❌ отменена" in t for t in labels), labels
