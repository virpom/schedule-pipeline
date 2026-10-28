"""Пара на 6-й строке под трёхстрочным объединением не теряется (план 171).

В файле «4 курс», группа ``ТЭф-23``, среда:

* ``B33:B35`` — одно объединение на три строки со значением «5 пара»;
* строка 35 — настоящая шестая пара «6-я пара с 18.05 до 19.40 - ...».

Старый парсер читал только B33 и B35 пропускал целиком (в B35 нет
номера пары), а регулярка не знала формата «N-я пара с X до Y» — оба
префикса сразу. Пара не попадала никуда, молча.

Вторая проверка — на живом файле `tests/fixtures/ochnoe-college.xlsx`:
там этот случай есть. Число пар не должно просесть, а пара ТЭф-23 на
среду, 6 пара должна читаться (в базе номер возьмётся из текста
«6-я пара»).
"""
from io import BytesIO

import openpyxl

from parsers.eios import parse_ochoe

SIXTH = (
    '6-я пара с 18.05 до 19.40 - \n '
    'Выполнение работ по профессии "Машинист-обходчик по котельному оборудованию"'
    "\nМордвин А.О."
)


def _book() -> bytes:
    """4 строки подряд: объединение B33:B35 и строка 35 с парой."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "4 курс"
    ws["C3"] = "ТЭф-23"
    ws["A25"] = "СРЕДА"
    ws["B33"] = "5 пара"
    ws["C33"] = " Психология общения\nЗенина С.В."
    ws["C34"] = "Иностранный язык в профессиональной деятельности\nГулиева Н.Г."
    ws["C35"] = SIXTH
    ws.merge_cells(start_row=33, start_column=2, end_row=35, end_column=2)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _sixth(lessons):
    return [l for l in lessons if l.para == 6]


def test_sixth_row_of_tall_merge_not_lost():
    lessons = parse_ochoe(_book())
    sixth = _sixth(lessons)
    assert len(sixth) == 1, lessons
    got = sixth[0]
    assert got.group == "ТЭф-23"
    assert got.day == 3
    assert got.teacher == "Мордвин А.О."
    assert got.subject.startswith("Выполнение работ по профессии")
    # Префикс «6-я пара с 18.05 до 19.40» снят в time_note, а не в предмете.
    assert "18.05" not in got.subject


def test_fifth_para_not_shadowed_by_sixth():
    """Шестая пара не должна лечь поверх пятой (или наоборот)."""
    lessons = parse_ochoe(_book())
    fifth = {(l.parity, l.subject) for l in lessons if l.para == 5}
    assert ("EVEN", "Психология общения") in fifth
    assert ("ODD", "Иностранный язык в профессиональной деятельности") in fifth


def test_live_fixture_sixth_para_present():
    """Живой файл: пара ТЭф-23 на среду посреди трёхстрочного объединения."""
    data = open("tests/fixtures/ochnoe-college.xlsx", "rb").read()
    lessons = parse_ochoe(data)
    assert len(lessons) >= 704  # было 704 до правки, потерь не прибавилось
    tar = [l for l in lessons if l.group == "ТЭф-23" and l.day == 3]
    assert any(l.para == 5 and l.parity == "EVEN"
               and l.subject == "Психология общения" for l in tar), tar
    assert any(l.para == 5 and l.parity == "ODD"
               and l.subject == "Иностранный язык в профессиональной деятельности"
               for l in tar), tar
    sixth = [l for l in tar if l.para == 6]
    assert sixth, tar
    assert any('Выполнение работ по профессии' in l.subject
               and l.teacher == "Мордвин А.О." for l in sixth), sixth
