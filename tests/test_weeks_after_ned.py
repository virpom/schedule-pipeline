"""«С нед. № 10» разбирается — пара идёт с 10-й недели (ранг 80).

WEEK_LIST_RE ждал «№» ПЕРЕД словом «нед.», а вуз пишет наоборот:
«С нед. № 10 - Сопротивление материалов». weeks оставался пустым, а
пустой weeks в _fits_week значит «ограничения нет» — пара показывалась
на всех неделях, включая те, где её ещё не было.

На проде таких строк 6 (группы ГД-25-1 и ГД-25-2, предмет
«Сопротивление материалов», пары 1 и 2).
"""
from parsers.vuz import (
    WEEK_LIST_RE,
    _parse_chunk,
    clean_subject,
    parse_week_list,
)


def test_reversed_order_parsed():
    m = WEEK_LIST_RE.search("С нед. № 10 - Сопротивление материалов (прак)")
    assert m, "обратный порядок по-прежнему не разбирается"
    assert parse_week_list(m.group(1)) == (10,)


def test_forward_order_still_parsed():
    """Старую запись не сломали."""
    m = WEEK_LIST_RE.search("(лек. №н. 1-7) Юрченко А.А.")
    assert parse_week_list(m.group(1)) == (1, 2, 3, 4, 5, 6, 7)


def test_range_after_reversed():
    m = WEEK_LIST_RE.search("нед. № 10-14 контрольная")
    assert parse_week_list(m.group(1)) == (10, 11, 12, 13, 14)


def test_dash_does_not_swallow():
    """Дефис-разделитель не должен попасть в список чисел.

    Если брать класс [\\d\\s,;\\-–], он съест «10 - » и parse_week_list
    не разберёт ничего.
    """
    m = WEEK_LIST_RE.search("С нед. № 10 - Сопротивление")
    assert m.group(1).strip() == "10", repr(m.group(1))


def test_week_lands_on_lesson():
    got = _parse_chunk(
        "С нед. № 10 - Сопротивление материалов (прак) Лозовский Э.Р.",
        "ГД-25-1@vuz", 3, 1, 1, False)
    assert len(got) == 1
    assert got[0].weeks == (10,), f"weeks={got[0].weeks}"
    assert got[0].parity == "ANY"


def test_subject_stripped():
    """От пометки недели не остаётся «С - » в названии."""
    assert clean_subject("С нед. № 10 - Сопротивление материалов (прак)") == \
        "Сопротивление материалов (прак)"


def test_plain_subject_untouched():
    assert clean_subject("Химия") == "Химия"
    assert clean_subject("Сопротивление материалов") == "Сопротивление материалов"


def test_lecture_and_practice_merge():
    """С общими неделями лекция и практика склеиваются в одну пару."""
    from parsers.vuz import _merge_same_subject
    a = _parse_chunk("С нед. № 10 - Сопротивление материалов (прак) Лозовский Э.Р.",
                     "ГД-25-1@vuz", 3, 1, 1, False)
    b = _parse_chunk("С нед. № 10 - Сопротивление материалов (лек) Лозовский Э.Р.",
                     "ГД-25-1@vuz", 3, 1, 2, False)
    merged = _merge_same_subject(a + b)
    assert len(merged) == 1
    assert merged[0].weeks == (10,)
