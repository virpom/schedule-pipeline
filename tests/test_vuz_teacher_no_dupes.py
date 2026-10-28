"""Преподаватель вуза не видит каждую пару дважды (план 137).

_user_lessons складывал два источника: college_lesson через
get_for_teacher_date и вузовский слой через _vuz_teacher_day. Но
college_lesson содержит и вузовские строки — материализация берёт все
группы из base_lesson, включая @vuz (1702 из 2974 строк на проде).

Проверено на проде до правки: у Кабышевой М.И. 28.10 — 7 строк из
college_lesson и 4 из вузовского слоя, и все 4 входят в эти 7.
В экране дня это 11 пар вместо 4.
"""
from types import SimpleNamespace

from tgbot.handlers.user import _drop_vuz_covered, _user_lessons  # noqa: F401


def _row(para, subject, group, room="", teacher="Иванов И.И."):
    return SimpleNamespace(para=para, subject=subject, group=group,
                           room=room, teacher=teacher, changed=False, action="")


def test_duplicate_vuz_row_dropped():
    college = [_row(2, "Прикладная физическая культура", "ИП-26-2@vuz"),
               _row(1, "История", "ДП-26")]
    vuz = [_row(2, "Прикладная физическая культура", None)]
    got = _drop_vuz_covered(college, vuz)
    assert len(got) == 1 and got[0].subject == "История", [g.subject for g in got]


def test_college_row_kept():
    college = [_row(1, "История", "ДП-26")]
    got = _drop_vuz_covered(college, [])
    assert len(got) == 1


def test_vuz_row_not_covered_kept():
    """Вузовская строка без пары в слое остаётся — она про замену."""
    college = [_row(2, "Физика", "ИП-26-2@vuz")]
    vuz = [_row(2, "Астрономия", None)]
    got = _drop_vuz_covered(college, vuz)
    assert len(got) == 1 and got[0].subject == "Физика", [g.subject for g in got]


def test_subject_normalisation():
    """«(лек.)» и «(лек)» — одна пара."""
    college = [_row(3, "Право (лек.)", "СА-26-2@vuz")]
    vuz = [_row(3, "Право (лек)", None)]
    assert _drop_vuz_covered(college, vuz) == []


def test_room_ignored_in_key():
    """Кабинет не входит в ключ — на нём источники и расходятся.

    Прод, Кабышева 28.10, пара 7: college_lesson отдал «М-401», слой —
    пусто. С кабинетом в ключе одна и та же пара оставалась дважды.
    """
    college = [_row(3, "Право", "СА-26-2@vuz", room="М-101")]
    vuz = [_row(3, "Право", None, room="")]
    assert _drop_vuz_covered(college, vuz) == []


def test_same_para_different_subject_kept():
    """Параллельные подгруппы — разные предметы, их не склеиваем."""
    college = [_row(7, "Физкультура", "СА-26-2@vuz")]
    vuz = [_row(7, "Иностранный", None)]
    assert len(_drop_vuz_covered(college, vuz)) == 1
