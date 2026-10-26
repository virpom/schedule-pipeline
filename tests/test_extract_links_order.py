"""Смысл ссылки важнее расширения файла.

План 034. `extract_links` проверял `.xlsx` первым, а смысловые признаки
— в `elif`. Стоило колледжу переименовать листок замен в `.xlsx`, как он
назначался «очной формой»: `parse_ochoe` вернул бы 0 пар,
`replace_base_lessons([])` стёр бы 704 строки колледжа, а замены не
обновились бы вовсе — 220 студентов увидели «Занятий нет».
"""
import pytest

from parsers import eios

BASE = "https://norvuz.ru/upload/timetable.ptk/%D0%A1%D0%9F%D0%9E/"


def _links(*names: str):
    html = "".join(f'<a href="{BASE}{n}">{n}</a>' for n in names)
    return eios.extract_links(html)


def test_current_page_still_parses():
    """Живая страница разбирается как раньше — все пять ссылок на местах."""
    links = _links("Очная форма.xlsx", "Листок замен.docx", "Заочная форма.docx",
                   "Понедельник.docx", "Стандартное.docx")
    assert links.ochoe
    assert links.zameny
    assert links.zaochnoe
    assert links.bells_monday
    assert links.bells_standard


def test_zameny_xlsx_does_not_become_ochoe():
    """Главный случай плана: листок замен в .xlsx.

    Без правки `endswith(".xlsx")` срабатывал первым, и листок замен
    уезжал в ochoe, а zameny оставался None.
    """
    links = _links("Очная форма.xlsx", "Листок замен.xlsx", "Заочная форма.docx")
    assert links.ochoe.endswith("Очная%20форма.xlsx") or "Очная" in links.ochoe
    assert links.zameny is not None
    assert "замен" in links.zameny.lower() or "%D0%B7%D0%B0%D0%BC%D0%B5%D0%BD" in links.zameny


def test_zaochnoe_xlsx_does_not_become_ochoe():
    """Заочка в .xlsx — тот же класс ошибки.

    У вуза уже есть `3-zaochnoe.xls` и `.xlsx` в одном каталоге, так
    что смена формата правдоподобна.
    """
    links = _links("Очная форма.xlsx", "Заочная форма.xlsx")
    assert "Очная" in links.ochoe
    assert links.zaochnoe is not None


def test_missing_ochoe_raises():
    """Нет очной формы — падаем громко, а не стираем расписание.

    `EiosParseError` уходит в тревогу админу. Тихая замена на пустой
    список стоила бы 704 строк.
    """
    with pytest.raises(eios.EiosParseError):
        _links("Листок замен.docx")


def test_xlsx_alone_is_not_enough():
    """`.xlsx` без слова «очная» не считается очной формой."""
    with pytest.raises(eios.EiosParseError):
        _links("какой-то файл.xlsx")


def test_bells_order_unchanged():
    """Звонки не перепутались: понедельник отдельно от стандартного."""
    links = _links("Очная форма.xlsx", "Понедельник.docx", "Стандартное.docx")
    assert links.bells_monday
    assert links.bells_standard
    assert links.bells_monday != links.bells_standard
