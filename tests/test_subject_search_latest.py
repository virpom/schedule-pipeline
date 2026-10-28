"""Поиск по предмету показывает последние занятия (план 114).

subject_answer брал matched[:5] до сортировки, а порядок matched задаёт
репозиторий, и у двух веток он противоположный:
get_all_for_group — date.desc(), get_all_for_teacher — date.

Значит преподаватель под заголовком «последние занятия» получал самые
СТАРЫЕ. Студенту везло случайно.
"""
import datetime
from types import SimpleNamespace

from tgbot.handlers.user import _subject_pick


def _l(date, para=1, subject="Математика"):
    return SimpleNamespace(date=date, para=para, subject=subject,
                           teacher="Т", room="", group="ДП-26",
                           changed=False, action="", time_note="")


def test_teacher_order_takes_newest():
    """Вход в порядке возрастания дат — как отдаёт get_all_for_teacher."""
    lessons = [_l(datetime.date(2026, 10, d)) for d in (13, 20, 21, 26, 27, 28)]
    got = _subject_pick(lessons, "математика")
    assert got[0].date == datetime.date(2026, 10, 28), got[0].date


def test_group_order_also_newest():
    """Вход в порядке убывания — как отдаёт get_all_for_group."""
    lessons = [_l(datetime.date(2026, 10, d)) for d in (28, 27, 26, 21, 20, 13)]
    got = _subject_pick(lessons, "математика")
    assert got[0].date == datetime.date(2026, 10, 28)


def test_limits_to_five():
    lessons = [_l(datetime.date(2026, 10, d)) for d in range(1, 15)]
    assert len(_subject_pick(lessons, "математика")) == 5


def test_filters_by_subject():
    lessons = [_l(datetime.date(2026, 10, 1), 1, "Математика"),
               _l(datetime.date(2026, 10, 2), 1, "Право")]
    got = _subject_pick(lessons, "матем")
    assert len(got) == 1 and got[0].subject == "Математика"


def test_empty_when_no_match():
    assert _subject_pick([_l(datetime.date(2026, 10, 1))], "химия") == []
