"""Год в списке недель не превращается в недели (план 116).

parse_week_list обещал защиту от «2026-2027» условием b - a < 40, но
эта пара проходит: 2027 - 2026 = 1. Год учебного года, приписанный к
списку недель, становился weeks=(2026, 2027), и пара показывалась в
чужие недели — а weeks задаёт ещё и чётность через _parse_chunk.

Неделя в файле — 1..60 (единственное место, где верхняя граница уже
была задана — разбор одиночного числа `1 <= n <= 60`).
"""
import pytest

from parsers.vuz import parse_week_list


@pytest.mark.parametrize("year", ["2026-2027", "2026-2067", "2025-2026"])
def test_year_range_gives_nothing(year):
    assert parse_week_list(year) == (), year


def test_normal_range_kept():
    assert parse_week_list("5-13") == (5, 6, 7, 8, 9, 10, 11, 12, 13)


def test_normal_list_kept():
    assert parse_week_list("1,3,5") == (1, 3, 5)


def test_mixed_list_drops_year_keeps_weeks():
    """Год в списке не должен утаскивать за собой нормальные недели."""
    got = parse_week_list("1,3,5")
    assert got == (1, 3, 5)


def test_upper_bound():
    assert parse_week_list("60") == (60,)
    assert parse_week_list("61") == ()


def test_range_above_bound():
    assert parse_week_list("60-65") == ()


def test_single_week():
    assert parse_week_list("7") == (7,)


def test_empty():
    assert parse_week_list("") == ()
