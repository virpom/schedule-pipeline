"""Шестая пара под чужим номером в B читается (план 171, вторая попытка).

В листе «4 курс» у ТЭф-23 объединение B33:B35 говорит «5 пара» на три
строки. Строка 33 — первая половина пятой пары, 34 — вторая половина,
а 35 — уже шестая пара: она написана в C35 как «6-я пара с 18.05 до
19.40 - …» и своего номера в B не имеет.

Парсер читал только строки, где в B написано «N пара», поэтому строка 35
пропускалась и шестой пары ТЭф-23 не было в базе вовсе.

Первая попытка (откачена 28.10.2026) растягивала «5 пара» из B на все
строки объединения — тогда строки 34 и 35 ложились поверх пятой, и на
фикстуре выходило 1392 пары вместо 704, 62 ключа с двумя предметами.
Правильно — брать номер только из текста самой ячейки.
"""
from collections import Counter
from pathlib import Path

from common.schedule import PARITY_EVEN, PARITY_ODD
from parsers.eios import parse_ochoe

FIXTURE = Path(__file__).parent / "fixtures" / "ochnoe-college.xlsx"


def _lessons():
    return parse_ochoe(FIXTURE.read_bytes())


def test_sixth_para_of_tef23_found():
    sixth = [l for l in _lessons()
             if l.group == "ТЭф-23" and l.day == 3 and l.para == 6]
    assert sixth, "шестая пара ТЭф-23 потерялась"
    assert {l.parity for l in sixth} == {PARITY_EVEN, PARITY_ODD}, sixth


def test_fifth_para_not_overwritten():
    """Строка 34 — вторая половина пятой, а не шестая пара."""
    fifth = [l for l in _lessons()
             if l.group == "ТЭф-23" and l.day == 3 and l.para == 5]
    assert len(fifth) == 2, fifth
    assert {l.parity for l in fifth} == {PARITY_EVEN, PARITY_ODD}


def test_time_prefix_stripped_from_subject():
    """«6-я пара с 18.05 до 19.40 - » уходит в time_note, не в название."""
    sixth = next(l for l in _lessons()
                 if l.group == "ТЭф-23" and l.day == 3 and l.para == 6)
    assert not sixth.subject.startswith("6-я пара"), sixth.subject
    assert "пара" not in sixth.subject.lower(), sixth.subject
    assert sixth.time_note, "время потерялось совсем"


def test_no_duplicate_slots():
    """Та самая проверка, которую провалила откаченная попытка."""
    counts = Counter((l.group, l.day, l.para, l.parity) for l in _lessons())
    dupes = {k: v for k, v in counts.items() if v > 1}
    assert not dupes, dupes


def test_own_para_ignores_rows_without_number():
    """Строка без номера ни в B, ни в тексте — не превращается в пару."""
    from parsers.eios import _own_para

    class Cell:
        def __init__(self, value):
            self.value = value

    class Sheet:
        def __init__(self, rows):
            self.rows = rows

        def cell(self, row, col):
            return Cell(self.rows.get((row, col)))

    sheet = Sheet({(5, 3): "Психология общения\nЗенина С.В."})
    assert _own_para(sheet, 5, {3: "ТЭф-23"}) is None
