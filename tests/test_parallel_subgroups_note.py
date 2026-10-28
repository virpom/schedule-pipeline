"""Параллельные подгруппы помечены «одновременно» (план 117).

В вузе часть занятий идёт параллельно по подгруппам: половина группы на
физкультуре, половина на иностранном, в одно время. В файле это две
пары на одном слоте, _merge_para_clash склеивает их через « / ».

Признака подгруппы в файле нет (проверил все листы на «подгрупп|пгр» —
0 совпадений), поэтому разделить «чей предмет» бот не может. Честный
максимум — сказать, что занятия одновременные: студент читал
«Физкультура / Иностранный» как одно занятие с двумя предметами.

На проде таких слотов три, в двух группах.
"""
import datetime

from common.schedule import format_day
from tgbot.services.schedule_layer import Slot

D = datetime.date(2026, 10, 28)


def _day(slots):
    return format_day(D, slots, {}, {}, "brief", "teacher", True)


def _merged():
    return Slot(7, "Физическая культура и спорт (лек.,прак. ) / Иностранный язык (прак. )",
                "Кабышева М.И. / Кострицына Н.А.", "М-310")


def test_parallel_marked():
    got = _day([_merged()])
    assert "одновременно" in got, got


def test_normal_pair_not_marked():
    got = _day([Slot(1, "Химия", "Иванов И.И.", "101")])
    assert "одновременно" not in got, got


def test_note_after_teachers():
    """Пометка идёт после преподавателей, а не разрывает блок."""
    lines = _day([_merged()]).split("\n")
    idx = next(i for i, l in enumerate(lines) if "одновременно" in l)
    assert "Кострицына" in lines[idx - 1], lines


def test_both_subjects_still_shown():
    got = _day([_merged()])
    assert "Физическая культура" in got
    assert "Иностранный язык" in got


def test_both_teachers_still_shown():
    got = _day([_merged()])
    assert "Кабышева" in got and "Кострицына" in got


def test_note_only_once_per_slot():
    got = _day([_merged(), Slot(8, "Химия", "И", "101")])
    assert got.count("одновременно") == 1, got
