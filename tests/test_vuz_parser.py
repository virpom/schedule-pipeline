"""Парсер расписания вуза на реальных файлах.

Файлы лежат в ``tests/fixtures`` — это настоящие выгрузки с norvuz.ru.
Тесты на выдуманных данных здесь бесполезны: половина сложности
парсера — в том, как именно устроены эти таблицы.
"""
import datetime
import pathlib

import pytest

from parsers import vuz

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def _load(name: str) -> bytes:
    path = FIXTURES / name
    if not path.exists():
        pytest.skip(f"нет файла {name}")
    return path.read_bytes()


@pytest.fixture(scope="module")
def full() -> vuz.VuzSheet:
    return vuz.parse(_load("1-ochnoe.xls"), "full")


@pytest.fixture(scope="module")
def part() -> vuz.VuzSheet:
    return vuz.parse(_load("2-ochno-zaochnoe.xls"), "part")


# --- структура файла ---------------------------------------------------------

def test_both_files_parse(full, part):
    assert len(full.lessons) > 1000
    assert len(part.lessons) > 400


def test_groups_have_vuz_suffix(full):
    assert all(g.name.endswith("@vuz") for g in full.groups)


def test_lessons_use_vuz_group_key(full):
    """Ключ группы несёт суффикс: иначе ЭК-23 вуза и колледжа склеятся."""
    assert all(l.group.endswith("@vuz") for l in full.lessons)


def test_faculties_detected(full):
    """В файле два факультета, у обоих разные варианты написания в шапке."""
    assert {g.faculty for g in full.groups} == {"FEU", "GTF"}


def test_courses_detected(full):
    assert {g.course for g in full.groups} == {1, 2, 3, 4, 5, 6}


def test_no_duplicate_groups_in_sheet(full):
    """«ГП-26» занимает две колонки в шапке — это один раз, не два."""
    names = [g.name for g in full.groups]
    assert len(names) == len(set(names))


# --- пары --------------------------------------------------------------------

def test_para_within_grid(full):
    """Сетка вуза — восемь пар, других номеров быть не может."""
    assert all(1 <= l.para <= 8 for l in full.lessons)


def test_weekday_within_week(full):
    assert all(1 <= l.weekday <= 7 for l in full.lessons)


def test_parity_values_known(full):
    assert {l.parity for l in full.lessons} <= {"ODD", "EVEN", "ANY"}


def test_both_parities_present(full):
    """Если парсер всегда ставит ANY — чётность сломана."""
    kinds = {l.parity for l in full.lessons}
    assert "ODD" in kinds and "EVEN" in kinds


def test_no_empty_subjects(full):
    assert all(l.subject.strip() for l in full.lessons)


def test_subjects_have_no_broken_brackets(full):
    """«(лек» без закрывающей скобки — признак поломки чистки."""
    for lesson in full.lessons:
        assert lesson.subject.count("(") == lesson.subject.count(")"), lesson.subject


def test_no_letter_spacing_left(full):
    """Разрядку «О с н о в ы» парсер обязан склеивать."""
    assert not any("О с н" in l.subject for l in full.lessons)


def test_teachers_extracted(full):
    """Почти у всех пар есть преподаватель — иначе split_teacher сломан."""
    with_teacher = sum(1 for l in full.lessons if l.teacher)
    assert with_teacher > len(full.lessons) * 0.95


def test_teacher_is_not_part_of_subject(full):
    """ФИО не должно оставаться в названии предмета."""
    for lesson in full.lessons:
        assert " И." not in lesson.subject
        assert " А." not in lesson.subject


# --- ключ базы ---------------------------------------------------------------

def test_slot_key_is_unique(full, part):
    """Ключ (группа, чётность, день, пара, недели) обязан быть уникальным.

    На нём держится уникальный индекс base_lesson. Если появятся дубли,
    синхронизация упадёт на вставке.
    """
    for sheet in (full, part):
        keys = [(l.group, l.parity, l.weekday, l.para, l.weeks)
                for l in sheet.lessons]
        assert len(keys) == len(set(keys))


def test_week_lists_are_sorted_and_unique(full):
    for lesson in full.lessons:
        if lesson.weeks:
            assert list(lesson.weeks) == sorted(set(lesson.weeks))
            assert all(1 <= w <= 60 for w in lesson.weeks)


def test_some_lessons_use_week_lists(full):
    """В файлах есть пары, заданные списком недель, а не чётностью."""
    assert sum(1 for l in full.lessons if l.weeks) > 100


# --- замены ------------------------------------------------------------------

def test_dated_cells_become_changes(full):
    """Датированные ячейки — замены, они не должны попасть в базу."""
    assert len(full.changes) > 20
    assert all(isinstance(c.date, datetime.date) for c in full.changes)


def test_changes_have_no_date_in_subject(full):
    for change in full.changes:
        assert "2026" not in change.subject


def test_changes_are_not_in_base_lessons(full):
    """Перенос не должен остаться и в постоянном расписании."""
    assert not any("перенос" in l.subject.lower() for l in full.lessons)


# --- устойчивость ------------------------------------------------------------

def test_broken_file_raises_parse_error():
    with pytest.raises(vuz.VuzParseError):
        vuz.parse(b"not an xls file at all")


def test_every_sheet_gives_lessons(full):
    """Каждый лист файла даёт пары и хотя бы одну группу.

    Лист, который молча разобрался в ноль пар, — это потерянная неделя
    расписания. Пусть лучше падает тест, чем студенты увидят пустой день.
    """
    import xlrd

    book = xlrd.open_workbook(
        str(FIXTURES / "1-ochnoe.xls"), formatting_info=True)
    for name in book.sheet_names():
        parsed = vuz.parse_sheet(book, name)
        assert parsed.groups, f"лист {name!r} без групп"
        assert parsed.lessons, f"лист {name!r} без пар"
