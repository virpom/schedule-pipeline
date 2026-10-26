"""Поиск преподавателя: однофамильцы не должны видеть чужие пары."""
from common.schedule import teacher_matches


def test_same_surname_different_initials_do_not_match():
    """«Чабаева А.В.» и «Чабаева А.Д.» — разные люди (план 107)."""
    assert not teacher_matches("Чабаева А.Д.", "Чабаева А.В.")
    assert not teacher_matches("Чабаева А.В.", "Чабаева А.Д.")
    assert not teacher_matches("Демченко И.В.", "Демченко О.Н.")
    assert not teacher_matches("Гулиева Н.Г.", "Гулиева Н.Н.")


def test_exact_name_matches():
    assert teacher_matches("Иванова З.Н.", "Иванова З.Н.")
    assert teacher_matches("Кокошка И. П.", "Кокошка И.П.")


def test_surname_without_initials_matches_wide():
    """Ищем по фамилии — показываем всех, иначе ничего не найдём."""
    assert teacher_matches("Коленова В.А.", "Коленова")
    assert teacher_matches("Ляшко", "Ляшко Д.В.")


def test_lost_initials_are_one_person():
    """У одного человека инициал бывает потерян в источнике."""
    assert teacher_matches("Городиский В.", "Городиский В.В.")
    assert teacher_matches("Воробьев М.С", "Воробьев М.С.")


def test_empty_name_does_not_match():
    assert not teacher_matches("Коленова В.А.", "")
    assert not teacher_matches("", "Коленова")
