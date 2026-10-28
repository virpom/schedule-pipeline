"""Понедельник знает время 6-й пары (план 167, хвост).

Сетка звонков одна на весь день: пара — 45 минут, перемена внутри пары
5 минут, между парами 10 минут. Понедельник сдвинут на +25 минут к
обычному дню (5-я пара начинается 16:45 вместо 16:20) — сдвинут весь
день, поэтому 6-я пара тоже на +25 от обычных 18:05.

Два независимых счёта дают одно и то же:
  от конца 5-й:      18:20 + 10 перемена = 18:30
  от обычного дня:   18:05 + 25 сдвиг    = 18:30
"""
import datetime

from common.schedule import format_bell, format_day
from infrastructure.database.models import BellSchedule
from infrastructure.database.repo.bell_schedule import DEFAULT_BELL
from tgbot.services.schedule_layer import Slot

MONDAY = datetime.date(2026, 11, 2)


def _t(value: str) -> datetime.time:
    hours, minutes = value.split(":")
    return datetime.time(int(hours), int(minutes))


def _bells():
    return {(d, c, p): BellSchedule(day_type=d, course_group=c, para=p,
                                   start=_t(s1), h1_end=_t(e1),
                                   h2_start=_t(s2), end=_t(e2))
            for d, c, p, s1, e1, s2, e2 in DEFAULT_BELL}


def test_monday_has_sixth_para_both_streams():
    have = {(c, p) for d, c, p, *_ in DEFAULT_BELL if d == "MONDAY"}
    assert ("I_IV", 6) in have, "понедельник I_IV без 6-й пары"
    assert ("II_III", 6) in have, "понедельник II_III без 6-й пары"


def test_monday_sixth_para_matches_the_grid():
    """45 + 5 + 45 и перемена 10 минут от конца 5-й пары."""
    bells = _bells()
    for cg in ("I_IV", "II_III"):
        sixth = bells[("MONDAY", cg, 6)]
        fifth = bells[("MONDAY", cg, 5)]
        assert sixth.start == _t("18:30")
        assert sixth.h1_end == _t("19:15")
        assert sixth.h2_start == _t("19:20")
        assert sixth.end == _t("20:05")
        assert fifth.end == _t("18:20")
        # перемена 10 минут и 5 минут внутри пары
        assert _minutes(fifth.end, sixth.start) == 10
        assert _minutes(sixth.h1_end, sixth.h2_start) == 5
        assert _minutes(sixth.start, sixth.h1_end) == 45


def test_monday_and_other_differ_by_the_same_shift():
    """Сдвиг понедельника постоянный: 5-я и 6-я сдвинуты одинаково."""
    bells = _bells()
    for cg in ("I_IV", "II_III"):
        shift5 = _minutes(bells[("OTHER", cg, 5)].start, bells[("MONDAY", cg, 5)].start)
        shift6 = _minutes(bells[("OTHER", cg, 6)].start, bells[("MONDAY", cg, 6)].start)
        assert shift5 == shift6 == 25


def test_day_card_shows_sixth_para_time():
    slot = Slot(para=6, subject="Архивное дело", teacher="Тест Т.Т.", room="101")
    text = format_day(MONDAY, [slot], _bells(), {}, meta="group", merge_groups=False)
    assert "18:30" in text and "20:05" in text, text


def test_bell_screen_lists_sixth_para():
    text = format_bell(_bells(), {})
    assert text.count("6 пара") >= 2, text


def _minutes(a, b) -> int:
    return (b.hour * 60 + b.minute) - (a.hour * 60 + a.minute)
