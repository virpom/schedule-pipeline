"""Склейка пар на одном слоте не теряет ни преподавателя, ни кабинет (81).

_merge_para_clash собирает пары, попавшие на один номер. Выходила она
при len(subjects) == 1 — и подгруппы иностранного языка с одинаковым
названием предмета теряли второго преподавателя: оставался первый,
второй исчезал без строки в логе.

Заодно нашлись два дефекта в самой склейке, которых в плане не было:
teacher склеивался как «{prev} / {slot}» без различения, поэтому у
одного преподавателя получалось «Иванов / Иванов»; room брался как
prev.room or slot.room, и второй кабинет терялся молча.

На проде таких пар сейчас 0 — дефект латентный, но именно эта функция
в плане 047 объявлена гарантией уникальности слота.
"""
from tgbot.services.schedule_layer import Slot
from tgbot.services.sync_eios import _merge_para_clash


def _merge(*slots):
    return _merge_para_clash(list(slots))


def test_same_subject_different_teacher():
    got = _merge(Slot(3, "Иностранный язык", "Иванов И.И.", ""),
                 Slot(3, "Иностранный язык", "Петров П.П.", ""))
    assert len(got) == 1
    assert "Иванов И.И." in got[0].teacher
    assert "Петров П.П." in got[0].teacher, "второй преподаватель потерян"


def test_same_subject_not_doubled():
    """Одинаковый предмет не склеивается сам с собой."""
    got = _merge(Slot(3, "Иностранный язык", "Иванов И.И.", ""),
                 Slot(3, "Иностранный язык", "Петров П.П.", ""))
    assert got[0].subject == "Иностранный язык", got[0].subject


def test_same_teacher_not_doubled():
    got = _merge(Slot(3, "Язык", "Иванов И.И.", "каб.5"),
                 Slot(3, "Язык", "Иванов И.И.", "каб.9"))
    assert got[0].teacher == "Иванов И.И.", f"получилось {got[0].teacher!r}"


def test_both_rooms_kept():
    got = _merge(Slot(3, "Язык", "Иванов И.И.", "каб.5"),
                 Slot(3, "Язык", "Иванов И.И.", "каб.9"))
    assert "каб.5" in got[0].room and "каб.9" in got[0].room, got[0].room


def test_room_from_second_only():
    """Кабинет есть только у второго слота — терять его незачем."""
    got = _merge(Slot(3, "Язык", "Иванов И.И.", ""),
                 Slot(3, "Язык", "Иванов И.И.", "каб.9"))
    assert got[0].room == "каб.9", got[0].room


def test_exact_duplicate_collapses():
    got = _merge(Slot(3, "Химия", "Иванов И.И.", "каб.5"),
                 Slot(3, "Химия", "Иванов И.И.", "каб.5"))
    assert len(got) == 1
    assert got[0].teacher == "Иванов И.И."
    assert got[0].room == "каб.5"


def test_different_subjects_still_joined():
    got = _merge(Slot(3, "Физкультура", "Иванов И.И.", "зал"),
                 Slot(3, "Право", "Петров П.П.", "каб.9"))
    assert got[0].subject == "Физкультура / Право"
    assert got[0].teacher == "Иванов И.И. / Петров П.П."


def test_three_way_accumulates():
    got = _merge(Slot(3, "Ф", "И", "з"), Slot(3, "П", "П", "к"),
                 Slot(3, "Х", "С", ""))
    assert got[0].subject == "Ф / П / Х"
    assert got[0].teacher == "И / П / С"


def test_unique_para_guarantee():
    """Гарантия плана 047: на один номер — один слот."""
    got = _merge(Slot(3, "Язык", "И", "5"), Slot(3, "Язык", "П", "9"),
                 Slot(3, "Право", "С", "7"))
    assert len(got) == 1
