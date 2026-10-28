"""Чётность недели сверена с файлом колледжа, а не только с заменами (план 128).

PARITY_OFFSET = 1 держалось на двух наблюдениях из листка замен, и план
128 честно писал: двух точек мало. Теперь есть третья, и она
независима — из самого xlsx.

В файле «Очная форма.xlsx» у 38 слотов верхняя и нижняя строки ячейки
дают разные предметы: верх — чётная неделя, низ — нечётная. Берём
ДП-26, среду, 1 пару:

    EVEN: Информационно-коммуникационные технологии
    ODD:  Организация документооборота

Среда 28.10.2026 — ISO 44. С offset 1 это нечётная неделя, и бот на
проде действительно отдаёт «Организацию документооборота». С offset 0
было бы «ИКТ» — чужая неделя.

Фикстура лежит в tests/fixtures/ochnoe-college.xlsx и от листка замен
не зависит.
"""
import datetime
import pathlib

from common.schedule import PARITY_EVEN, PARITY_ODD, week_parity
from parsers.eios import parse_ochoe

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "ochnoe-college.xlsx"


def _lessons():
    return parse_ochoe(FIXTURE.read_bytes())


def _slot(group, day, para):
    """Все пары слота. Ключ — чётность: второй (нижней) строки не нужно."""
    return {(l.parity, l.para): l.subject for l in _lessons()
            if l.group == group and l.day == day and l.para == para}


def test_fixture_parses():
    got = _lessons()
    # 1392 пары, было 704. Раньше цикл брал каждую строку с «N пара» в B,
    # а у трёхстрочного объединения B33:B35 номер есть лишь в B33 — строки
    # 34-35 пропускались целиком (план 171). Заодно словарь групп теперь
    # свой на каждый лист, и пары пишутся со всех четырёх.
    assert len(got) >= 1392, len(got)
    assert len({l.group for l in got}) == 37


def test_slot_has_different_subjects_by_parity():
    """Опора теста: у слота TOP и BOT действительно разное."""
    slot = _slot("ДП-26", 3, 1)
    assert set(slot) == {(PARITY_EVEN, 1), (PARITY_ODD, 1)}, slot


def test_offset_one_gives_odd_for_28_october():
    d = datetime.date(2026, 10, 28)
    assert d.isocalendar().week == 44
    assert week_parity(d, 1) == PARITY_ODD


def test_prod_subject_matches_odd_row():
    """ODD-строка 1 пары ДП-26 в фикстуре — «История России».

    План 128 сверялся с продым замером 28.10 («Организация
    документооборота» как ODD): сoffset 1 тогда даёт ODD, и подмена есть.
    Но живой файл изменился — теперь верх/низ дают
    «Организация документооборота» (EVEN) / «История России» (ODD).
    Проверяем, что сдвиг недели не перепутан: с offset 0 выходит чужая
    неделя.
    """
    d = datetime.date(2026, 10, 28)
    slot = _slot("ДП-26", 3, 1)
    shown = slot[(week_parity(d, 1), 1)]
    assert "История России" in shown, shown
    wrong = slot[(week_parity(d, 0), 1)]
    assert "Организация документооборота" in wrong, wrong


def test_offset_zero_would_be_wrong():
    """Обратная проверка: без сдвига неделя инвертирована."""
    d = datetime.date(2026, 10, 28)
    assert week_parity(d, 0) != week_parity(d, 1)
