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


def test_merged_groups_deduplicated():
    """Одна группа не должна повторяться в подписи.

    У вуза на один слот бывает несколько пар с разными списками недель.
    После фильтра по неделе они приходят отдельными строками, и подпись
    превращалась в «СА - 26-2, СА - 26-2, СА - 26-2».
    """
    lessons = [FakeLesson(6, "Инженерная геодезия", "СА - 26-2@vuz",
                          "204", "Кокошка И.П.") for _ in range(3)]
    text = format_day(dt.date(2026, 10, 27), lessons, {}, {}, meta="group",
                      merge_groups=True)
    assert text.count("СА - 26-2") == 1
    assert text.count("6)") == 1


def test_vuz_bell_differs_from_college():
    """У вуза своя сетка: 8 пар, без «Разговоров о важном»."""
    from common.schedule import format_bell

    class BS:
        def __init__(self, para, start, end):
            self.para = para
            self.start, self.end = start, end
            self.h1_end = self.h2_start = None

    bell = {}
    for p, a, b in [(1, dt.time(8, 40), dt.time(10, 10)),
                    (8, dt.time(20, 30), dt.time(22, 0))]:
        for day_type in ("MONDAY", "OTHER"):
            bell[(day_type, "VUZ", p)] = BS(p, a, b)
            bell[(day_type, "I_IV", p)] = BS(p, a, b)
    bell[("MONDAY", "ALL", 0)] = BS(0, dt.time(9, 0), dt.time(9, 20))

    vuz = format_bell(bell, {}, vuz=True)
    assert "вуза" in vuz
    assert "Разговоры о важном" not in vuz
    assert "курс" not in vuz
    assert "8 пара" in vuz

    college = format_bell(bell, {}, vuz=False)
    assert "Разговоры о важном" in college


def test_preview_matches_student_view():
    """Предпросмотр редактора обязан совпадать с экраном студента.

    Раньше он собирался своей рукой: без времени пары, с другим
    порядком строк и без группы. Редактор видел одно, студент другое.
    """
    import datetime as _dt

    from common.schedule import format_day
    from tgbot.handlers.editor import preview_text
    from tgbot.services.schedule_layer import Slot

    class BS:
        def __init__(self, para, start, end):
            self.para, self.start, self.end = para, start, end
            self.h1_end = self.h2_start = None

    date = _dt.date(2026, 10, 26)
    bell = {("MONDAY", "I_IV", 2): BS(2, _dt.time(11, 10), _dt.time(12, 45))}
    slots = [Slot(2, "Обществознание", "Иванов И.И.", "204", group="АТ-26")]

    preview = preview_text("АТ-26", date, slots, bell, {}, "I_IV")
    # meta="teacher" — ровно то, что видит студент: под парой преподаватель
    # и кабинет, а не своя же группа.
    student = format_day(date, slots, bell, {}, detail="full", meta="teacher",
                         group_course_group={"АТ-26": "I_IV"})
    assert preview == student
    assert "11:10–12:45" in preview, "нет времени пары — как у студента"
    assert "Иванов И.И." in preview, "нет преподавателя"
    assert "АТ-26 · 204" not in preview, "превью показывает группу вместо препода"
