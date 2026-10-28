"""Поиск преподавателя склеивает поток так же, как день и неделя (147).

Экран дня и неделя флаг `merge_groups` передавали, а `format_teacher_results`
(«👨‍🏫 найди преподавателя») — нет, и там же физкультура потока снова была
пятью строками на одну пару. Это третье место той же поломки.
"""
import datetime
import inspect

from common.schedule import format_day, format_teacher_results
from tgbot.handlers import user as user_mod
from tgbot.services.schedule_layer import Slot

GROUPS = ("ИП-24@vuz", "ИС-24@vuz", "ИЭ-24@vuz", "СА-24@vuz", "СМ-24@vuz")


def _entries():
    d = datetime.date(2026, 11, 9)
    return [(d, [Slot(1, "Прикладная физическая культура", "Бацунов С.Н.", "зал",
                      group=g) for g in GROUPS])]


def test_result_has_merge_flag():
    assert "merge_groups" in inspect.signature(format_teacher_results).parameters


def test_search_merge_collapses_stream():
    """Пять групп одного преподавателя на одну пару — одна строка."""
    merged = format_teacher_results(_entries(), {}, {}, merge_groups=True)
    plain = format_teacher_results(_entries(), {}, {})
    assert merged.count("Прикладная физическая культура") == 1, merged
    assert plain.count("Прикладная физическая культура") == len(GROUPS), plain
    # Ни одна группа потока не потеряна: склейка, а не отбрасывание.
    for g in GROUPS:
        assert g.split("@")[0] in merged, merged


def test_search_matches_day_screen():
    """Один и тот же набор даёт одинаковое число пар на обоих экранах."""
    day = format_day(datetime.date(2026, 11, 9), _entries()[0][1], {}, {},
                     meta="group", show_rov=False, merge_groups=True)
    search = format_teacher_results(_entries(), {}, {}, merge_groups=True)
    subj = "Прикладная физическая культура"
    assert day.count(subj) == search.count(subj) == 1


def test_search_merge_off_by_default():
    assert inspect.signature(
        format_teacher_results).parameters["merge_groups"].default is False


def test_handler_passes_flag():
    assert "merge_groups=_is_teacher(user)" in inspect.getsource(user_mod.teacher_answer)
