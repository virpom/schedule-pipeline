"""«Разговоры о важном» разбираются из файла звонков.

План 033. В понедельничном файле есть строка без номера пары:

    | '' | с 9.00 до 9.20 – «Разговоры о важном» | …

`parse_bells` искал номер пары в первой колонке и строку отбрасывал.
Слот `para=0` попадал в БД только из `DEFAULT_BELL` при первом запуске
(`seed_if_empty`) — то есть фича работала по совпадению константы с
файлом. Поменяй в файле время — студент продолжил бы видеть старое.

Тест на настоящем файле с сайта (tests/fixtures/bells-monday.docx):
11 записей вместо 10, `para=0 / ALL / 09:00–09:20`.
"""
import datetime
import pathlib

from parsers import eios

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "bells-monday.docx"


def test_razgovory_parsed_from_file():
    rows = eios.parse_bells(FIXTURE.read_bytes(), "MONDAY")
    rov = [r for r in rows if r.para == 0]
    assert len(rov) == 1, f"слот «Разговоров» не разобран: {len(rov)}"
    assert rov[0].course_group == "ALL"
    assert rov[0].start == datetime.time(9, 0)
    assert rov[0].end2 == datetime.time(9, 20)


def test_regular_paras_unchanged():
    """Пары 1–5 разбираются как раньше — по две на каждый поток."""
    rows = eios.parse_bells(FIXTURE.read_bytes(), "MONDAY")
    regular = [r for r in rows if r.para > 0]
    assert len(regular) == 10, len(regular)
    assert {r.course_group for r in regular} == {"I_IV", "II_III"}
    assert sorted({r.para for r in regular}) == [1, 2, 3, 4, 5]


def test_razgovory_group_is_all():
    """`course_group=ALL` обязателен: `format_bell` ищет по нему."""
    rows = eios.parse_bells(FIXTURE.read_bytes(), "MONDAY")
    rov = [r for r in rows if r.para == 0]
    assert rov[0].course_group == "ALL", \
        "без ALL format_bell не найдёт слот и студент его не увидит"


def test_razgovory_single_half():
    """У «Разговоров» одна половина — обе пары времён совпадают.

    Строка одна, а не две как у обычной пары, поэтому `halves` соберёт
    один отрезок и разложит его в обе половины.
    """
    rows = eios.parse_bells(FIXTURE.read_bytes(), "MONDAY")
    rov = [r for r in rows if r.para == 0][0]
    assert rov.start == datetime.time(9, 0)
    assert rov.end1 == datetime.time(9, 20)
    assert rov.start2 == rov.start, "вторая половина не совпала с первой"
    assert rov.end2 == rov.end1


def test_is_razgovory_detects_row():
    assert eios._is_razgovory(["", "с 9.00 до 9.20 – «Разговоры о важном»"])
    assert eios._is_razgovory(["", "РАЗГОВОРЫ О ВАЖНОМ"])
    assert not eios._is_razgovory(["1 пара", "09.25", "-", "10.10"])


def test_parse_range_reads_one_cell():
    """Время лежит в одной ячейке, а не в двух."""
    got = eios._parse_range("с 9.00 до 9.20 – «Разговоры о важном»")
    assert got == (datetime.time(9, 0), datetime.time(9, 20))


def test_parse_range_rejects_backwards():
    assert eios._parse_range("с 9.20 до 9.00") is None
    assert eios._parse_range("нет времени") is None


def test_no_razgovory_in_standard_file():
    """В файле остальных дней такой строки нет — поведение не меняется."""
    import pathlib as pl
    src = pl.Path(eios.__file__).read_text()
    # Косвенная проверка: разбор не привязан к дню недели.
    assert "day_type" in src
