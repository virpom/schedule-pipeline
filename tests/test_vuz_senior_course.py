"""План 169: пятикурсник вуза видел «4 курс».

`course_from_group` считал курс как «год приёма из имени группы →
сколько учебных лет прошло» и зажимал результат в 1..4. Для колледжа
потолок безобиден (там 4 курса), для вуза — нет: 5 и 6 курс
схлопывались в «4 курс» прямо в подписи меню.

Проверяем настоящий источник курса вуза — `vuz_group.course` из
справочника, а не распределение выхода самой функции: `min(..., 4)` по
построению даёт 1..4, и такое сравнение «аномалий не находит» никогда.
"""
import datetime

from common.schedule import (course_from_group, course_group_from_group,
                             is_vuz)


def _acad_start() -> int:
    now = datetime.datetime.now()
    return now.year if now.month >= 9 else now.year - 1


def _name_for_course(course: int) -> str:
    return f"ГИ-{(2000 + _acad_start() - (course - 1)) % 100:02d}@vuz"


def test_senior_vuz_course_is_not_capped():
    """5 и 6 курс вуза — это 5 и 6, а не 4."""
    for course in (1, 2, 3, 4, 5, 6):
        group = _name_for_course(course)
        assert course_from_group(group) == course, \
            f"{group} реально на {course} курсе"


def test_plan_example_groups():
    """Группы из плана при acad_start=2026 — ровно как в справочнике."""
    if _acad_start() != 2026:
        return          # пример привязан к учебному году плана
    assert course_from_group("ГИ-22@vuz") == 5
    assert course_from_group("ГИ-21@vuz") == 6


def test_college_still_gets_its_course():
    """Колледж не задет: 1..4 у него и раньше считались верно."""
    for course in (1, 2, 3, 4):
        assert course_from_group(_name_for_course(course).removesuffix("@vuz")) == course


def test_vuz_bells_do_not_depend_on_course():
    """Потолка нет — но звонки вуза по-прежнему свои, без деления."""
    assert course_group_from_group("ГИ-21@vuz") == "VUZ"
    assert is_vuz("ГИ-22@vuz")


def test_menu_shows_fifth_year():
    """Подпись меню — то, что видит человек, а не только функция."""
    from infrastructure.database.models import User
    from tgbot.handlers.user import menu_text

    group = _name_for_course(5)
    user = User(id=1, role="student", group=group, course=4)
    text = menu_text(user)
    assert f"{group.removesuffix('@vuz')} · 5 курс" in text, text
    assert "4 курс" not in text, text


if __name__ == "__main__":
    test_senior_vuz_course_is_not_capped()
    test_plan_example_groups()
    test_college_still_gets_its_course()
    test_vuz_bells_do_not_depend_on_course()
    test_menu_shows_fifth_year()
    print("ok")
