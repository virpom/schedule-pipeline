"""Экран дня вуза: дубли в тексте и потерянные варианты в кнопках.

План 153. У вуза на один (пара) бывает несколько строк с разными
``weeks`` — на живой группе АП-25оз@vuz, вторник, ANY их шесть на пару 7.
``get_day`` без ``week`` отдаёт их все, и ``base_day_text`` печатал
«7) Компьютерное моделирование» четыре раза подряд.

Кнопки собирались из ``{s.para: s for s in slots}``: последний слот пары 7
затирал предыдущие три. Староста видел одну дисциплину из четырёх и не
мог добраться до остальных — а текст выше называл все.
"""
from tgbot.handlers import editor
from tgbot.services.schedule_layer import Slot


def vuz_slots():
    """Ровно шесть слотов из плана 153 (пара 7 — четыре варианта)."""
    return [
        Slot(7, "Компьютерное моделирование, ч.1", weeks="13"),
        Slot(7, "Основы военной подготовки (лек.)", weeks="5,6"),
        Slot(7, "Основы военной подготовки", weeks="7,8"),
        Slot(7, "Компьютерное моделирование, ч.1 (лек.)", weeks="9,10,11,12"),
        Slot(8, "Основы военной подготовки (прак.)", weeks="5,6,7,8"),
        Slot(8, "Компьютерное моделирование (прак.)", weeks="9,10,11,12,13"),
    ]


def test_text_has_one_line_per_para():
    text = editor.base_day_text("АП-25оз@vuz", 2, "ANY", vuz_slots())
    assert text.count("<b>7)</b>") == 1, text
    assert text.count("<b>8)</b>") == 1, text


def test_text_lists_every_variant_exactly_once():
    text = editor.base_day_text("АП-25оз@vuz", 2, "ANY", vuz_slots())
    for subject in ("Компьютерное моделирование, ч.1 <i>",
                    "Компьютерное моделирование, ч.1 (лек.) <i>",
                    "Основы военной подготовки (лек.) <i>",
                    "Основы военной подготовки <i>"):
        assert text.count(subject) == 1, (subject, text)


def test_text_keeps_weeks_of_each_variant():
    """Без недель четыре одинаковых названия неразличимы."""
    text = editor.base_day_text("АП-25оз@vuz", 2, "ANY", vuz_slots())
    for weeks in ("13", "5,6", "7,8", "9,10,11,12"):
        assert f"({weeks})" in text, (weeks, text)


def test_college_line_unchanged():
    """Колледж: один вариант на пару — строка как была, без недель."""
    slot = Slot(3, "Математика", "Иванов И.И.", "101")
    text = editor.base_day_text("ДП-26", 1, "ANY", [slot])
    assert "<b>3)</b> Математика\n      Иванов И.И. · 101" in text, text
    assert "недели" not in text


def test_keyboard_keeps_all_variants_of_a_para():
    """Кнопка пары 7 сообщает, что вариантов четыре, а не один."""
    kb = editor.paras_kb(2, "ANY", vuz_slots(), last=8)
    labels = [b.text for row in kb.inline_keyboard for b in row]
    row7 = next(t for t in labels if t.startswith("7)"))
    assert row7.endswith("+3"), f"кнопка пары 7 не говорит про 4 варианта: {row7}"
    row8 = next(t for t in labels if t.startswith("8)"))
    assert row8.endswith("+1"), row8
    # Пары без вариантов не обрастают пометкой.
    assert next(t for t in labels if t.startswith("1)")) == "1) — пусто"
