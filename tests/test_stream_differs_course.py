"""Склейка групп разных курсов не обещает чужое время (план 165).

_merge_groups пишет группы в `group` через запятую, а `
course_from_group` берёт ПЕРВЫЕ две цифры строки. Для «ПРк-25, ЮР-24А»
это 25, то есть 2 курс — преподаватель получал звонки первой группы, а
вторая половина пары и обед у неё свои.

Проверено на проде: 6 колледжных склеек из разных курсов, в том числе
«ДОУф-26, ЭК-23» (1 и 4 курс) и «ПРк-25, ЮР-24А» (2 и 3).

Признак — по КУРСУ, а не по потоку: ПРк-25 и ЮР-24А оба II_III, по
потокам разницы не видно.
"""
from common.schedule import stream_differs


def test_different_courses_detected():
    assert stream_differs("ПРк-25, ЮР-24А") is True
    assert stream_differs("ДОУф-26, ЭК-23") is True


def test_same_course_not_flagged():
    assert stream_differs("СМф-26, ЮРф-26") is False
    assert stream_differs("ИП-26@vuz, ИС-26@vuz") is False


def test_single_group_not_flagged():
    assert stream_differs("ДП-26") is False
    assert stream_differs("") is False
    assert stream_differs(None) is False


def test_off_by_one_year_detected():
    """25 и 24 — соседние курсы, но звонки у них разные."""
    assert stream_differs("ПРк-25, ЮР-24А") is True


def _slot(group):
    from tgbot.services.schedule_layer import Slot
    return Slot(para=4, subject="Физическая культура", teacher="Ляшко Д.В.",
                room="спортзал", group=group)


def test_teacher_card_warns_about_mixed_courses():
    """Предупреждение нужно преподавателю, а не только студенту.

    На проде 29.10.2026 у Ляшко Д.В. склеились «ПРк-25, ЮР-24А» — 2 и 3
    курс. В карточке преподавателя печатается ветка meta="teacher", и
    раньше предупреждение стояло только в ветке группы: тот, кто делает
    склейку и кому подставляются чужие звонки, не видел ничего.
    """
    import datetime
    from common.schedule import format_day

    text = format_day(datetime.date(2026, 10, 29), [_slot("ПРк-25, ЮР-24А")],
                      {}, {}, detail="full", meta="teacher", merge_groups=False)
    assert "группы разных курсов" in text, text


def test_student_card_still_warns():
    import datetime
    from common.schedule import format_day

    text = format_day(datetime.date(2026, 10, 29), [_slot("ДОУф-26, ЭК-23")],
                      {}, {}, detail="full", meta="group", merge_groups=False)
    assert "группы разных курсов" in text, text


def test_same_course_card_says_nothing():
    import datetime
    from common.schedule import format_day

    text = format_day(datetime.date(2026, 10, 29), [_slot("СМф-26, ЮРф-26")],
                      {}, {}, detail="full", meta="teacher", merge_groups=False)
    assert "курсов" not in text, text
