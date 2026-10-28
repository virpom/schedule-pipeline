"""Время в начале ячейки вуза — не дата (ранг 79).

Настоящая причина оказалась не в том, что писало план. План 079 говорил
про INLINE_TIME_RE без re.I, и это тоже верно («С 18.50» с заглавной
не разбиралось). Но главное — is_move звал DATE_RE, а DATE_RE видит
«18.50» как 18-е число 50-го месяца. Ячейка считалась разовой парой на
дату и выбрасывалась целиком.

На проде из-за этого висели две замены вуза с временем в названии:
  «с 18.30 Правоохранительные органы (прак.)»   — в паре 7, но текст цел
  «с 18.50. - Организация деятельности ЦБ (лек)» — в паре 4 вместо 7
"""
from parsers.vuz import DATE_RE, INLINE_TIME_RE, inline_para, is_move


# --- изолированные функции ---------------------------------------------------

def test_time_is_not_move():
    assert not is_move("с 18.50. - Организация деятельности Банка (лек)")


def test_time_not_treated_as_date():
    """DATE_RE действительно ловит 18.50 — на этом и был баг."""
    assert DATE_RE.search("с 18.50 - Организация"), "условие бага изменилось"


def test_real_date_still_move():
    assert is_move("09.11.2026 - Неорганическая химия")
    assert is_move("26.10 замена")


def test_word_perenos_still_move():
    assert is_move("с 18.50 перенос")


def test_inline_time_case_insensitive():
    assert INLINE_TIME_RE.match("С 18.50 - Средства")
    assert inline_para("С 18.50 - Средства")[0] == 7


def test_inline_time_lowercase():
    assert inline_para("с 18.50. - Организация")[0] == 7


def test_offgrid_time_clears_name():
    """18.30 нет в сетке, но название всё равно чистим."""
    para, rest = inline_para("с 18.30 Правоохранительные органы (прак.)")
    assert para is None
    assert rest == "Правоохранительные органы (прак.)", rest


def test_on_grid_clean_name():
    para, rest = inline_para("с 17.10 - Средства автоматизации")
    assert para == 6
    assert rest == "Средства автоматизации"


# --- сквозной путь через разбор ячейки ---------------------------------------

class _FakeSheet:
    merged_cells: list = []
    nrows = 9
    ncols = 9

    def __init__(self, cells):
        self._cells = cells

    def cell_value(self, r, c):
        return self._cells.get((r, c), "")


def _cell(text, para=4):
    from parsers.vuz import Sheet, _cell_lessons
    return _cell_lessons(Sheet(_FakeSheet({(0, 0): text})), 0, 0,
                         "ГП-26@vuz", 3, para, 1, False, None)


def test_cell_time_sets_para():
    """«с 18.50» — это 7-я пара, а не 4-я из ряда."""
    got = _cell("с 18.50. - Организация деятельности Центрального Банка (лек)")
    assert len(got) == 1
    assert got[0].para == 7, f"пара {got[0].para}, ожидали 7"
    assert not got[0].subject.startswith("с "), got[0].subject


def test_cell_offgrid_keeps_row_para():
    """18.30 нет в сетке — номер берём из ряда, но название чистое."""
    got = _cell("с 18.30 Правоохранительные органы (прак.)", para=4)
    assert len(got) == 1
    assert got[0].para == 4
    assert got[0].subject == "Правоохранительные органы (прак.)"


def test_cell_date_still_skipped():
    """Настоящая дата по-прежнему не идёт в базовое расписание."""
    assert _cell("09.11.2026 - Неорганическая химия") == []
