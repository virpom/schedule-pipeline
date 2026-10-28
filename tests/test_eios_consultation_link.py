"""Ссылка на консультации не перетирает очное расписание (инцидент 28.10).

Колледж выложил на страницу второй файл «Очная форма.xlsx» — в папке
«Консультация преподавателей». Настоящее расписание лежит в «СПО/Очная
форма.xlsx».

extract_links проверял только имя файла («очная» + .xlsx), поэтому обе
ссылки проходили, и выигрывала последняя на странице — консультации.
Парсер получал 17 строк «Расписание консультаций» вместо расписания,
возвращал 0 пар, синк падал с «не найдено ни одной пары» каждые 5
минут, а старостам улетели два алерта.

Урок про `unquote(url).lower()`, а не `unquote(url.lower())`: lower()
портит percent-encoding («%D0%9A» -> «%d0%9a», unquote даёт битый
символ), и проверка молча не срабатывает.
"""
from urllib.parse import quote

from parsers.eios import extract_links

REAL = "/upload/timetable.ptk/СПО/Очная форма.xlsx"
CONSULT = "/upload/timetable.ptk/Консультация преподавателей/Очная форма.xlsx"


def _page(*paths):
    return "\n".join(f'<a href="{quote(p)}">файл</a>' for p in paths)


def test_real_schedule_wins_over_consultation():
    links = extract_links(_page(REAL, CONSULT), base_url="https://norvuz.ru")
    assert "СПО" in quote(links.ochoe, safe="") or "%D0%A1%D0%9F%D0%9E" in links.ochoe, links.ochoe


def test_real_schedule_wins_in_any_order():
    links = extract_links(_page(CONSULT, REAL), base_url="https://norvuz.ru")
    assert "%D0%A1%D0%9F%D0%9E" in links.ochoe, links.ochoe


def test_consultation_only_raises():
    """Если настоящего файла нет — честная ошибка «ссылка не найдена»,
    а не молчаливое использование файла консультаций (17 строк вместо
    расписания, 0 пар, стёртые base_lesson)."""
    import pytest
    from parsers.eios import EiosParseError
    with pytest.raises(EiosParseError):
        extract_links(_page(CONSULT), base_url="https://norvuz.ru")


def test_zameny_not_confused():
    links = extract_links(_page(REAL, "/upload/timetable.ptk/СПО/Листок замен.docx"),
                          base_url="https://norvuz.ru")
    assert "замен" in links.zameny.lower() or "%D0%B7%D0%B0%D0%BC%D0%B5%D0%BD" in links.zameny


def test_zaochnoe_separate():
    links = extract_links(_page(REAL, "/upload/timetable.ptk/СПО/Заочная форма.docx"),
                          base_url="https://norvuz.ru")
    assert links.zaochnoe is not None
    assert "%D0%A1%D0%9F%D0%9E/%D0%97" in links.zaochnoe or "заоч" in links.zaochnoe.lower()


def test_first_match_wins():
    """Из двух подходящих берётся первая на странице, а не последняя.

    Колледж уже один раз положил рядом файл-двойник: тогда выигрывала
    последняя ссылка, и парсер разбирал не тот документ.
    """
    from urllib.parse import unquote
    real = "/upload/timetable.ptk/СПО/Очная форма.xlsx"
    dup = "/upload/timetable.ptk/СПО/Очная форма (1).xlsx"
    links = extract_links(_page(real, dup), base_url="https://norvuz.ru")
    assert unquote(links.ochoe).endswith("Очная форма.xlsx"), links.ochoe
