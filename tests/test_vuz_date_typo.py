"""Опечатка в годе не создаёт замену на 2022 год (план 106).

В файле вуза «1-ochnoe.xls» методист напечатал «06.11.20226. — перенос
на 18.11.2026»: хотел 06.11.2026, приписал лишнюю 6.

DATE_RE был `(?:\\d{2,4})?` — жадный, и забирал «2022», обрезая
лишнюю цифру: на экране дата верная по смыслу, а в базе 2022-11-06,
на четыре года в прошлом, навсегда.

Проверено на фикстуре: до правки из 213 замен вуза две были 2022 года,
после — ноль.
"""
from collections import Counter

from parsers.vuz import parse, parse_date

TYPED = "06.11.20226. - перенос на 18.11.2026"


def test_typo_year_uses_default():
    got = parse_date(TYPED, 2026)
    assert got is not None
    assert got.year == 2026, got


def test_typo_does_not_swallow_next_digit():
    """Год из пяти цифр не год."""
    from parsers.vuz import DATE_RE
    got = [m.group(0) for m in DATE_RE.finditer(TYPED)]
    assert "06.11.20226" not in got
    assert any(g.startswith("18.11.2026") for g in got), got


def test_normal_dates_unchanged():
    assert parse_date("09.11.2026", 2026).isoformat() == "2026-11-09"
    assert parse_date("26.10", 2026).isoformat() == "2026-10-26"
    assert parse_date("01.09.26", 2026).isoformat() == "2026-09-01"


def test_fixture_has_no_old_years():
    r = parse(open("tests/fixtures/1-ochnoe.xls", "rb").read())
    years = Counter(c.date.year for c in r.changes)
    assert years.get(2022, 0) == 0, years
    assert set(years) == {2026}, years
