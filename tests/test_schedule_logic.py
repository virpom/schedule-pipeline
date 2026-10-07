from common.schedule import course_group_from_course
from infrastructure.database.repo.user import majority_course_groups


def test_course_group_from_course():
    assert course_group_from_course(None) is None
    assert course_group_from_course(1) == "I_IV"
    assert course_group_from_course(2) == "I_IV"
    assert course_group_from_course(3) == "II_III"
    assert course_group_from_course(4) == "II_III"


def test_majority_course_groups():
    rows = [("ЭК-25", 2), ("ЭК-25", 2), ("ЭК-25", 3)]
    assert majority_course_groups(rows) == {"ЭК-25": "I_IV"}

    rows = [("ТЭ-26ФП", 1), ("ТЭ-26ФП", 1), ("ТЭ-26ФП", 1)]
    assert majority_course_groups(rows) == {"ТЭ-26ФП": "I_IV"}


def test_majority_tie_falls_back():
    rows = [("А-25", 2), ("А-25", 3)]
    assert majority_course_groups(rows) == {}


def test_majority_skips_none():
    rows = [("Б-24", None), ("Б-24", None)]
    assert majority_course_groups(rows) == {}


if __name__ == "__main__":
    test_course_group_from_course()
    test_majority_course_groups()
    test_majority_tie_falls_back()
    test_majority_skips_none()
    print("OK")
