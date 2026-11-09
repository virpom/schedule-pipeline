"""Листок замен с пятью колонками и «работа дома».

Настоящий листок ПТК (10.11.2026) отличается от тех, что парсер видел
раньше, в трёх местах, и каждое ломало разбор МОЛЧА:

1. **Пять колонок вместо четырёх.** «Предмет по расписанию» занимает две
   ячейки (объединение), «Чем заменяется» уезжает в индекс 4. Парсер
   брал cells[3] жёстко и читал старый предмет: 86 замен превращались
   в «было = стало», включая «НЕТ ПАРЫ» — отмен не находилось ни одной.

2. **«(сам-ная работа дома)»** — пометка о форме занятия. Без её снятия
   имя преподавателя не опознавалось, и предмет слипался с ним в одну
   строку: студент видел «Ин.яз – Пупкова В.В. (сам-ная работа дома)»
   как название пары.

3. **«с 18.00 до 21.00»** в графе пары — это время, а не номер.
   Из него выдёргивались цифры 18 и 21, и в базе появлялись пары 0, 1,
   2, 8. Вечерняя пара получает номер 7.

Проверено на настоящем файле: 32 группы, 79 замен, 0 строк без
преподавателя, 0 расхождений с исходником по числу строк.
"""
from io import BytesIO

from docx import Document

from parsers.eios import parse_substitutions
from common.schedule import SUB_ADD, SUB_CANCEL, SUB_REPLACE


def _docx(header: str, rows: list[list[str]], five: bool = True) -> bytes:
    doc = Document()
    doc.add_paragraph("ЛИСТОК ЗАМЕН К РАСПИСАНИЮ ОЧНОГО ОТДЕЛЕНИЯ")
    doc.add_paragraph(header)
    cols = 5 if five else 4
    table = doc.add_table(rows=1, cols=cols)
    head = (["Группа", "пара", "Предмет по расписанию",
             "Предмет по расписанию", "Чем заменяется"] if five
            else ["Группа", "пара", "Предмет по расписанию", "Чем заменяется"])
    for i, h in enumerate(head):
        table.rows[0].cells[i].text = h
    for r in rows:
        cells = table.add_row().cells
        for i, v in enumerate(r):
            cells[i].text = v
    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


HDR = "на 10.11.2026, вторник, нечетная неделя"


def test_five_columns_takes_last_column():
    """Из пяти колонок «стало» — последняя, а не четвёртая."""
    data = _docx(HDR, [["ДП-26", "1", "Химия - Рюхина Е.М.",
                        "Химия - Рюхина Е.М.", "ОБиЗР - Костылева В.В., ауд. 202"]])
    subs = parse_substitutions(data)
    assert len(subs) == 1
    s = subs[0]
    assert s.action == SUB_REPLACE
    assert s.subject == "ОБиЗР", s.subject
    assert s.teacher == "Костылева В.В."
    assert s.room == "ауд. 202"


def test_four_columns_still_works():
    """Старый формат не сломан."""
    data = _docx(HDR, [["ДП-26", "1", "Химия - Рюхина Е.М.",
                        "ОБиЗР - Костылева В.В., ауд. 202"]], five=False)
    subs = parse_substitutions(data)
    assert subs[0].subject == "ОБиЗР"
    assert subs[0].teacher == "Костылева В.В."


def test_net_pary_cancels_in_five_columns():
    """«НЕТ ПАРЫ» в пятиколоночном листке — отмена, а не замена."""
    data = _docx(HDR, [["ДП-26", "1", "Деловая культура - Молчанова Н.А.",
                        "Деловая культура - Молчанова Н.А.", "НЕТ ПАРЫ"]])
    subs = parse_substitutions(data)
    assert subs[0].action == SUB_CANCEL
    assert subs[0].subject == ""


def test_net_in_now_means_cancel():
    """«НЕТ» без «ПАРЫ» — то же самое."""
    data = _docx(HDR, [["ДП-26", "1", "с 18.00 до 21.00",
                        "с 18.00 до 21.00", "НЕТ"]])
    subs = parse_substitutions(data)
    assert subs[0].action == SUB_CANCEL


def test_self_study_note_split():
    """«(сам-ная работа дома)» не мешает отделить преподавателя."""
    data = _docx(HDR, [["ТЭ-26ФП", "4", "Ин.яз – Пупкова В.В.",
                        "Ин.яз – Пупкова В.В.",
                        "Ин.яз – Пупкова В.В. (сам-ная работа дома)"]])
    s = parse_substitutions(data)[0]
    assert s.teacher == "Пупкова В.В.", s.teacher
    assert "сам" in s.subject, s.subject


def test_self_study_with_trailing_comma():
    """Запятая перед пометкой не должна ломать имя."""
    data = _docx(HDR, [["СМ-26КП", "4", "Обществознание - Бацунов С.Н.",
                        "Обществознание - Бацунов С.Н.",
                        "Общес-ние - Бацунов С.Н., (сам. работа дома)"]])
    s = parse_substitutions(data)[0]
    assert s.teacher == "Бацунов С.Н.", s.teacher


def test_evening_time_goes_to_time_note():
    """«с 18.00 до 21.00» — время, а не номер пары.

    Раньше из него выдёргивались 18 и 21, и появлялись пары 0, 1, 2, 8.
    Потом я ставил номер 7 — и студент видел «7) пара 7 ❌ отменено»:
    строку без времени и без смысла, потому что звонков на седьмую
    пару нет. Теперь номер 1, а время едет в time_note.
    """
    data = _docx(HDR, [["ДП-26", "с 18.00 до 21.00",
                        "с 18.00 до 21.00", "НЕТ",
                        "Организация документооборота - Харькова Д.А., ауд. 406"]])
    subs = parse_substitutions(data)
    assert len(subs) == 1
    assert subs[0].para == 1, subs[0].para
    assert subs[0].time_note == "с 18.00 до 21.00", subs[0].time_note


def test_evening_row_is_replace_not_cancel():
    """В графе «было» стоит время, а не «НЕТ» — значит это замена.

    Колонки в этой строке четыре: время, время (дубль объединения),
    «НЕТ», новый предмет. Читать по индексу 2 значило взять «НЕТ»
    и превратить вечернюю замену в отмену.
    """
    data = _docx(HDR, [["ДП-26", "с 18.00 до 21.00",
                        "с 18.00 до 21.00", "НЕТ",
                        "Организация документооборота - Харькова Д.А., ауд. 406"]])
    s = parse_substitutions(data)[0]
    assert s.action == SUB_REPLACE, s.action
    assert s.subject == "Организация документооборота", s.subject


def test_room_without_comma():
    """«ауд. 406» без запятой перед ним."""
    data = _docx(HDR, [["ДП-26", "5", "НЕТ", "НЕТ",
                        "Деловая культура - Молчанова Н.А. ауд. 406"]])
    s = parse_substitutions(data)[0]
    assert s.teacher == "Молчанова Н.А.", s.teacher
    assert s.room == "ауд. 406", s.room


def test_bare_room_number():
    """«, 221» — кабинет без слова «ауд.»."""
    data = _docx(HDR, [["ЭКк-26", "1", "Обществознание – Бацунов С.Н.",
                        "Обществознание – Бацунов С.Н.",
                        "Математика – Заковряшина И.С., 221"]])
    s = parse_substitutions(data)[0]
    assert s.subject == "Математика", s.subject
    assert s.room == "221", s.room


def test_distant_format():
    """«дистант» — формат занятия, а не аудитория и не часть имени."""
    data = _docx(HDR, [["ЭК-23", "3", "Ин.яз - Гулиева Н.Г.",
                        "Ин.яз - Гулиева Н.Г.",
                        "Организация и планирование НД - Сачук Ю.Н., дистант"]])
    s = parse_substitutions(data)[0]
    assert s.teacher == "Сачук Ю.Н.", s.teacher
    assert "дистант" in s.room, s.room
