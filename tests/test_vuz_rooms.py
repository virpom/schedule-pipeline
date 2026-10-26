"""Кабинеты вуза и ссылки на онлайн-пары доходят до студента.

План 021. `parse_sheet` отбрасывал колонки «ауд» вместе со служебными,
и поле `room` у `VuzLesson` оставалось пустым всегда. На проде это
означало ноль кабинетов во всей базе: `base_lesson` вуз — 1954 пары,
`room` пуст у всех.

Дороже всего терялись 46 ссылок на Teams в `1-ochnoe.xls`: без них
дистанционную пару невозможно посетить вообще.
"""

from parsers.vuz import VuzLesson, parse, parse_sheet

FIXTURE = "tests/fixtures/1-ochnoe.xls"
FIXTURE2 = "tests/fixtures/2-ochno-zaochnoe.xls"


def _lessons(path):
    result = parse(open(path, "rb").read())
    return result.lessons if hasattr(result, "lessons") else result


def test_rooms_are_parsed():
    """Главное: кабинеты больше не теряются."""
    lessons = _lessons(FIXTURE)
    with_room = [l for l in lessons if l.room]
    assert with_room, "ни одного кабинета — план 021 вернулся"
    # В файле 717 ячеек «ауд», из них часть — служебные пометки.
    assert len(with_room) > 500, f"кабинетов всего {len(with_room)}"


def test_online_links_are_parsed():
    """Ссылки на онлайн-пары — самая дорогая потеря.

    Не только Teams: в файле есть и Яндекс-Телемост. Оба вида — URL,
    и обрезать их по 64 символам нельзя: огрызок не открывается.
    """
    lessons = _lessons(FIXTURE)
    links = [l for l in lessons if l.room.lower().startswith("http")]
    assert links, "ссылок на онлайн-пары нет"
    for lesson in links:
        assert lesson.room.startswith(("https://", "http://")), lesson.room
        # Обрезка по 64 символам ломала бы ссылку.
        assert len(lesson.room) > 40


def test_room_is_short_and_clean():
    """В поле кабинета не должно быть текста пары.

    При горизонтальном мерже в колонку «ауд» перетекает название
    предмета с преподавателем. Раньше это попадало в `room` целиком.
    """
    lessons = _lessons(FIXTURE)
    for lesson in lessons:
        if not lesson.room or lesson.room.lower().startswith("http"):
            continue
        assert len(lesson.room) <= 20, f"длинное значение: {lesson.room!r}"
        assert len(lesson.room.split()) == 1, f"несколько слов: {lesson.room!r}"


def test_junk_values_are_dropped():
    """«н.»/«ч.» — чётность недели, «Айка»/«ЭИОС» — электронная среда.

    Ни то ни другое кабинетом не является.
    """
    lessons = _lessons(FIXTURE)
    junk = {"н.", "ч.", "н", "ч", "айка", "эиос"}
    bad = [l.room for l in lessons if l.room.strip().lower() in junk]
    assert not bad, f"мусор в кабинетах: {bad[:5]}"


def test_second_file_also_has_rooms():
    """Не только первый лист: заочный файл тоже."""
    lessons = _lessons(FIXTURE2)
    with_room = [l for l in lessons if l.room]
    assert len(with_room) > 150, f"кабинетов {len(with_room)}"


def test_rooms_do_not_break_dedup():
    """Две пары одного предмета в разных кабинетах — не дубль.

    Иначе подгруппы, занимающиеся в разных аудиториях, схлопнулись бы
    в одну строку и половина студентов увидела бы чужой кабинет.
    """
    a = VuzLesson("ДП-26@vuz", 1, 1, "ANY", "Физика", "Иванов И.И.",
                  room="М-101", weeks=())
    b = VuzLesson("ДП-26@vuz", 1, 1, "ANY", "Физика", "Иванов И.И.",
                  room="М-102", weeks=())
    from parsers.vuz import _dedupe
    assert len(_dedupe([a, b])) == 2


def test_groups_still_parsed():
    """Группы не потерялись при переходе на тройки."""
    import xlrd
    book = xlrd.open_workbook(FIXTURE)
    sheet = parse_sheet(book, book.sheet_names()[0])
    assert sheet.groups, "групп нет"
    assert all(g.name.endswith("@vuz") for g in sheet.groups)
