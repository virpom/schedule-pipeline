"""Показ расписания преподавателя: дубли, пустое имя, склейка потока."""
import datetime as dt

from common.schedule import format_day, teacher_base, teacher_matches


class FakeLesson:
    def __init__(self, para, subject, group, room="", teacher="", changed=False):
        self.para = self.para_end = para
        self.subject, self.group, self.room = subject, group, room
        self.teacher, self.changed = teacher, changed


def test_initials_normalized_to_single_form():
    """«И. П.» и «И.П.» — один человек, а не два в списке."""
    assert teacher_base("Кокошка И. П.") == teacher_base("Кокошка И.П.") == "Кокошка И.П."
    assert teacher_base("Вересова Е. А.") == "Вересова Е.А."
    # Хвост после запятой отрезается.
    assert teacher_base("Ляшко Д.В., 1-ая подгруппа") == "Ляшко Д.В."


def test_teacher_matches_both_spellings():
    assert teacher_matches("Кокошка И. П.", "Кокошка И.П.")
    assert teacher_matches("Кокошка И.П.", "Кокошка И. П.")
    assert teacher_matches("Кокошка И. П.", "Кокошка")


def test_merged_groups_shown_in_one_line():
    """Поток из трёх групп — одна пара, а не три одинаковые строки."""
    lessons = [FakeLesson(1, "Физкультура", g, "СЗ", "Преображенский А.В.")
               for g in ("АП-25@vuz", "ИС-25@vuz", "ИЭ-25@vuz")]
    text = format_day(dt.date(2026, 10, 26), lessons, {}, {}, meta="group",
                      merge_groups=True)

    assert text.count("1)") == 1, "пара должна быть одна"
    assert "АП-25, ИС-25, ИЭ-25" in text
    assert "@vuz" not in text, "служебный суффикс не должен попадать в текст"


def test_different_subjects_not_merged():
    """Склеиваем только одинаковые пары: разные предметы остаются раздельно."""
    lessons = [FakeLesson(1, "Математика", "А-1", teacher="Иванов А.В."),
               FakeLesson(1, "Физика", "А-2", teacher="Иванов А.В.")]
    text = format_day(dt.date(2026, 10, 26), lessons, {}, {}, meta="group",
                      merge_groups=True)
    assert text.count("1)") == 2


def test_merge_off_keeps_teacher_days_apart():
    """Без склейки (студент) каждая строка на месте."""
    lessons = [FakeLesson(1, "Физкультура", g, teacher="Преображенский А.В.")
               for g in ("АП-25@vuz", "ИС-25@vuz")]
    text = format_day(dt.date(2026, 10, 26), lessons, {}, {}, meta="group")
    assert text.count("1)") == 2
