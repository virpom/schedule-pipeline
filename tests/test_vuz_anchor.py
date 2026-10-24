"""Якорь учебной недели вуза: проверка сходимости и ручная установка."""
import datetime as dt

from parsers.vuz import VuzChange, VuzLesson
from tgbot.services.sync_vuz import (
    DEFAULT_ANCHOR,
    anchor_fit,
    anchor_looks_off,
    vuz_week,
)


def lesson(group, weeks):
    return VuzLesson(group=group, weekday=1, para=1, parity="ANY",
                     subject="Предмет", teacher="", weeks=weeks)


def change(group, date):
    return VuzChange(group=group, date=date, para=1, subject="Замена")


def test_anchor_fit_counts_matching_dates():
    """Даты замен должны попадать в недели, где у группы есть пары."""
    lessons = [lesson("ЭК-26@vuz", (9, 10, 11, 12))]
    changes = [change("ЭК-26@vuz", dt.date(2026, 10, 26)),   # неделя 9
               change("ЭК-26@vuz", dt.date(2026, 11, 2))]    # неделя 10
    good, total = anchor_fit(lessons, changes, DEFAULT_ANCHOR)
    assert (good, total) == (2, 2)


def test_anchor_fit_ignores_groups_without_weeks():
    """Пары без списка недель ничего не говорят о якоре."""
    lessons = [lesson("ЭК-26@vuz", ())]
    changes = [change("ЭК-26@vuz", dt.date(2026, 10, 26))]
    assert anchor_fit(lessons, changes, DEFAULT_ANCHOR) == (0, 0)


def test_shifted_anchor_detected():
    """Сдвиг на семестр виден сразу: почти все даты уходят из диапазона."""
    # Диапазон недель широкий — как в реальном файле.
    lessons = [lesson("ЭК-26@vuz", tuple(range(1, 19)))]
    changes = [change("ЭК-26@vuz", dt.date(2026, 10, 26) + dt.timedelta(days=7 * i))
               for i in range(12)]

    good, total = anchor_fit(lessons, changes, DEFAULT_ANCHOR)
    assert not anchor_looks_off(good, total)

    shifted = DEFAULT_ANCHOR + dt.timedelta(days=7 * 26)
    good2, total2 = anchor_fit(lessons, changes, shifted)
    assert anchor_looks_off(good2, total2)


def test_small_sample_does_not_raise_alarm():
    """На двух датах статистики нет — тревожить админа незачем."""
    assert not anchor_looks_off(0, 2)
    assert not anchor_looks_off(0, 9)
    assert anchor_looks_off(0, 10)


def test_vuz_week_counts_from_anchor():
    assert vuz_week(dt.date(2026, 8, 31), dt.date(2026, 8, 31)) == 1
    assert vuz_week(dt.date(2026, 9, 7), dt.date(2026, 8, 31)) == 2
    assert vuz_week(dt.date(2026, 10, 26), dt.date(2026, 8, 31)) == 9
