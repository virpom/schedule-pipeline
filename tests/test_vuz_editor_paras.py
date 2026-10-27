"""Редактор вуза показывает 8 слотов, колледжа — 6.

План 042. `paras_kb` и `sub_slots_kb` перебирали `range(1, MAX_PARA + 1)`
с общей границей 6, а сетка вуза — восемь пар.

На проде это 572 пары, недоступные для правки:
  para=6: 70, para=7: 268, para=8: 234.

Хуже: староста, увидев «5) — пусто» на дне с парой на 6-м слоте, ставил
новую на 5-й — и студент видел две пары вместо одной.
"""
import inspect

from common.schedule import MAX_PARA, MAX_PARA_VUZ, max_para
from tgbot.handlers import editor


def test_college_limit():
    assert max_para("ДП-26") == 6
    assert max_para("ДП-26") == MAX_PARA


def test_vuz_limit():
    assert max_para("ЭК-24@vuz") == 8
    assert max_para("ЭК-24@vuz") == MAX_PARA_VUZ


def test_none_group_defaults_to_college():
    """Без группы — граница колледжа, как было."""
    assert max_para(None) == MAX_PARA


def test_paras_kb_vuz_has_eight_rows():
    kb = editor.paras_kb(1, "ANY", [], last=8)
    # 8 пар + кнопка «Назад»
    assert len(kb.inline_keyboard) == 9, len(kb.inline_keyboard)


def test_paras_kb_college_has_six_rows():
    kb = editor.paras_kb(1, "ANY", [])
    assert len(kb.inline_keyboard) == 7, len(kb.inline_keyboard)


def test_sub_slots_kb_vuz_has_eight_rows():
    kb = editor.sub_slots_kb("2026-11-03", [], {}, last=8)
    assert len(kb.inline_keyboard) == 9, len(kb.inline_keyboard)


def test_sub_slots_kb_college_has_six_rows():
    kb = editor.sub_slots_kb("2026-11-03", [], {})
    assert len(kb.inline_keyboard) == 7, len(kb.inline_keyboard)


def test_callers_pass_group_limit():
    """Все вызовы передают границу по группе, а не общую константу."""
    src = inspect.getsource(editor)
    code = "\n".join(line.split("#", 1)[0] for line in src.splitlines())
    n = code.count("last=max_para(group)")
    assert n == 6, f"передано в {n} местах, ожидали 6"


def test_para_seven_visible_for_vuz():
    """Седьмая пара — самый частый слот вуза (268 пар на проде)."""
    kb = editor.paras_kb(1, "ANY", [], last=8)
    labels = [b.text for row in kb.inline_keyboard for b in row]
    assert any(t.startswith("7)") for t in labels), labels
    assert any(t.startswith("8)") for t in labels), labels
