"""Дефис и тире в фамилии, двое в одной паре (план 090).

Две беды в teacher_base, обе видны на проде:

1. Дефис и тире с пробелами вокруг не нормализовались. «Мурашова-Росс
   А.В.» и «Мурашова - Росс А.В.» — один человек, а в списке
   преподавателей две записи.

2. Строка «Багомедова У.М., Левочкина Н.А.» — это двое, но split(",")[0]
   отрезал вторую. Левочкину нельзя было найти поиском вообще: её не
   было ни в списке, ни в teacher_matches.

Вторая беда оказалась не только про запятую: старый тест фиксировал
«Ляшко Д.В., 1-ая подгруппа» -> «Ляшко Д.В.», и это другой случай.
Запятая бывает хвостом и бывает вторым человеком — отличаем по виду
второй части (фамилия с инициалами).
"""

from common.schedule import teacher_base, teacher_matches
from infrastructure.database.repo.college_lesson import _clean_teacher_names


# --- дефис и тире -----------------------------------------------------------

def test_dash_variants_collapse():
    forms = ["Мурашова-Росс А.В.", "Мурашова - Росс А.В.", "Мурашова – Росс А.В."]
    assert len({teacher_base(f) for f in forms}) == 1, forms
    assert teacher_base(forms[0]) == "Мурашова-Росс А.В."


def test_dash_not_touching_single_surname():
    assert teacher_base("Иванов И.И.") == "Иванов И.И."


def test_initials_still_collapse():
    assert teacher_base("Кокошка И. П.") == "Кокошка И.П."


def test_teacher_list_no_dash_duplicate():
    got = _clean_teacher_names(["Мурашова-Росс А.В.", "Мурашова - Росс А.В."])
    assert got == ["Мурашова-Росс А.В."], got


# --- двое в одной паре ------------------------------------------------------

def test_hyphen_surname_kept():
    """Фамилию через дефис не делим."""
    assert teacher_base("Мурашова-Росс А.В.") == "Мурашова-Росс А.В."


def test_second_person_kept():
    got = teacher_base("Багомедова У.М., Левочкина Н.А.")
    assert "Багомедова У.М." in got
    assert "Левочкина Н.А." in got, f"второй человек потерян: {got!r}"


def test_tail_after_comma_still_cut():
    """Хвост вида «1-ая подгруппа» — не человек."""
    assert teacher_base("Ляшко Д.В., 1-ая подгруппа") == "Ляшко Д.В."
    assert teacher_base("Левочкина Н.А., подгруппа 2") == "Левочкина Н.А."


def test_both_people_in_list():
    got = _clean_teacher_names(["Багомедова У.М., Левочкина Н.А.", "Иванов И.И."])
    assert "Левочкина Н.А." in got, got
    assert "Багомедова У.М." in got, got


def test_search_finds_second_person():
    pair = "Багомедова У.М., Левочкина Н.А."
    assert teacher_matches(pair, "Левочкина Н.А.")
    assert teacher_matches(pair, "Багомедова У.М.")
    assert teacher_matches(pair, "Левочкина")
    assert not teacher_matches(pair, "Иванов И.И.")


def test_plain_pair_unchanged():
    assert _clean_teacher_names(["Ляшко", "Ляшко Д.В."]) == ["Ляшко Д.В."]
