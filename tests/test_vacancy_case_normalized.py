"""«вакансия» со строчной — та же пустая ставка, что «Вакансия» (план 159).

На проде в поле преподавателя встречались оба написания: 54 пары
«Вакансия» и 8 «вакансия» в college_lesson, 25 и 4 в base_lesson.

Список преподавателей от обоих избавлен ещё в 097: фильтр
_NOT_A_PERSON сравнивает без учёта регистра. А карточка пары печатает
поле как есть (format_day) — и на 8 парах студент видел «вакансия» со
строчной, как опечатку в расписании. clean_teacher приводил к канону
только ФИО с инициалами, вакансия уходила дословно.
"""
import datetime
from types import SimpleNamespace

import pytest

from common.schedule import format_day
from parsers.eios import clean_teacher, split_subject_teacher, split_substitution_text


@pytest.mark.parametrize("raw", ["вакансия", "Вакансия", "ВАКАНСИЯ",
                                 "  вакансия  "])
def test_vacancy_case_canonical(raw):
    assert clean_teacher(raw) == "Вакансия", raw


def test_cell_with_lowercase_vacancy():
    assert split_subject_teacher("Геология вакансия") == ("Геология", "Вакансия")
    assert split_subject_teacher("Геология\nвакансия") == ("Геология", "Вакансия")


def test_substitution_with_lowercase_vacancy():
    assert split_substitution_text("Геология – вакансия, ауд. 202") == (
        "Геология", "Вакансия", "ауд. 202")


def test_teacher_flag_in_schedule_no_longer_lowercase():
    lesson = SimpleNamespace(
        para=2, para_end=2, subject="Геология",
        teacher=clean_teacher("вакансия"), room="ауд. 202", group="ПРф-23",
        changed=False, action="", time_note="", comment="", weeks=None)

    class _NoBell(dict):
        def get(self, *_args, **_kwargs):
            return None

    text = format_day(datetime.date(2026, 11, 9), [lesson], _NoBell(),
                      _NoBell(), show_rov=False, group_course_group={},
                      merge_groups=False)
    assert "Вакансия · ауд. 202" in text, text
    assert "вакансия ·" not in text, text


def test_real_names_untouched():
    assert clean_teacher("Баканчи О.П.") == "Баканчи О.П."
    assert clean_teacher("Иванов И.И.") == "Иванов И.И."
