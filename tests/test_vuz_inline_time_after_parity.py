"""«н. с 12.10» — это время пары, а не дата переноса.

В файле вуза внутри ячейки бывает указано время начала: «н. с 12.10
Основы микропроцессорной техники (лек. №н. 7,9; пр. №н. 13,15)».

DATE_RE видел здесь «12.10» и принимал за 12 октября, is_move() отвечал
True, и вся пара выбрасывалась как разовая замена. На проде так пропал
весь четверг у АП-23: ноль пар вместо восьми.

Вторая половина того же дефекта: часть после «;» — продолжение того же
предмета, своего времени у неё нет. Она получала номер строки, и из
одной ячейки выходили две пары (п3 и п2) с одним предметом.

Проверено на файле 1-ochnoe.xls: было 1353 пары, стало 1401; выиграли
18 групп-дней, больше всех АП-23 четверг (+8) и ЭП-23 пятница (+6).
"""
from pathlib import Path

import pytest

from parsers.vuz import INLINE_TIME_RE, _cell_lessons, inline_para, is_move

FIXTURE = Path(__file__).parent / "fixtures" / "vuz-1-ochnoe.xls"


def test_parity_prefix_before_inline_time():
    """«н. с 12.10» — время, префикс чётности не мешает."""
    text = "н. с 12.10 Основы микропроцессорной техники (лек. №н. 7,9)"
    assert INLINE_TIME_RE.match(text)
    assert is_move(text) is False, "пара выброшена как перенос"
    assert inline_para(text)[0] == 3


def test_uppercase_s_also_works():
    text = "ч. С 13.50 Технологические процессы"
    assert is_move(text) is False
    assert inline_para(text)[0] == 4


def test_real_date_still_treated_as_move():
    """Настоящая дата переноса по-прежнему не попадает в базу."""
    text = "н.Введение в профиль (лек) Левченко И.В. 28.10.2026 - пары нет"
    assert is_move(text) is True


def test_second_chunk_inherits_inline_time():
    """Продолжение предмета после «;» не получает номер строки."""
    class _Cell:
        def __init__(self, value):
            self.value = value

    class _Sheet:
        def text(self, row, col):
            return _Cell(self.rows.get((row, col), "")).value

        def raw(self, row, col):
            return self.rows.get((row, col), "")

        def span(self, row, col):
            return (row, col)

        _origin = {}

    sheet = _Sheet()
    sheet.rows = {(1, 0): "н. с 12.10 Основы микропроцессорной техники "
                          "(лек.№н. 7,9; пр. №н. 13,15) Мозгунов Д.В."}
    got = _cell_lessons(sheet, 1, 0, "АП-23@vuz", 4, 2, upper=True)
    assert got, "ячейка не разобралась"
    assert {l.para for l in got} == {3}, [l.para for l in got]


@pytest.mark.skipif(not FIXTURE.exists(), reason="нет фикстуры файла вуза")
def test_real_file_thursday_not_lost():
    """Регресс на живом файле: четверг АП-23 не пустой."""
    from parsers.vuz import parse

    sheet = parse(FIXTURE.read_bytes(), "full")
    thursday = [l for l in sheet.lessons
                if l.group == "АП-23@vuz" and l.weekday == 4]
    assert thursday, "четверг АП-23 снова потерян"
    assert {l.para for l in thursday} >= {3, 4}, {l.para for l in thursday}
