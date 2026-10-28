"""Склейка лекции и практики не теряет второго преподавателя (ранг 78).

Две функции склеивают пары вуза в одну строку, и преподавателя они
обрабатывали по-разному: _merge_slot_clash дописывал через запятую,
_merge_same_subject — только если поле пустое. Если лекцию ведёт один,
а практику другой, второй исчезал молча.

Студент шёл на практику, не зная преподавателя; в расписании второго
преподавателя пары тоже не было — она записана на первого.
"""
from parsers.vuz import PARITY_ODD as ODD, VuzLesson, _merge_same_subject, _merge_slot_clash


def _lesson(subject, teacher, kind_date=None, parity=ODD, weeks=()):
    return VuzLesson(
        group="ИП-26@vuz", weekday=2, para=3, parity=parity,
        subject=subject, teacher=teacher, weeks=weeks)


def test_second_teacher_kept():
    got = _merge_same_subject([
        _lesson("Страхование (лек.)", "Иванов И.И."),
        _lesson("Страхование (прак.)", "Петров П.П."),
    ])
    assert len(got) == 1
    assert "Иванов И.И." in got[0].teacher
    assert "Петров П.П." in got[0].teacher, "второй преподаватель потерян"


def test_same_teacher_not_duplicated():
    got = _merge_same_subject([
        _lesson("Страхование (лек.)", "Иванов И.И."),
        _lesson("Страхование (прак.)", "Иванов И.И."),
    ])
    assert got[0].teacher == "Иванов И.И."


def test_empty_teacher_filled():
    got = _merge_same_subject([
        _lesson("Страхование (лек.)", ""),
        _lesson("Страхование (прак.)", "Петров П.П."),
    ])
    assert got[0].teacher == "Петров П.П."


def test_both_functions_agree():
    """Один и тот же приём в обеих функциях."""
    a = _merge_same_subject([
        _lesson("Страхование (лек.)", "Иванов И.И."),
        _lesson("Страхование (прак.)", "Петров П.П."),
    ])[0].teacher
    b = _merge_slot_clash([
        _lesson("Страхование", "Иванов И.И."),
        _lesson("Право", "Петров П.П."),
    ])[0].teacher
    assert a == b, f"разные приёмы: {a!r} vs {b!r}"
