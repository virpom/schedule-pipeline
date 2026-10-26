"""Шестая пара не должна пропадать из сетки звонков и из редактора.

План 023. `format_bell` собирал пары через `range(1, 6)` — жёстко 1..5.
Пара 6 существует: в звонках для неё есть строки (OTHER/I_IV и
OTHER/II_III, 18:05–19:40), а в `college_lesson` на проде **73 пары** с
`para=6` за 12 дней окна — это не «три пары в истории», как считал план.

Студент видел в дне «6) 18:05–19:40 Горные машины», а на экране звонков
шестой пары не было — ответа «во сколько 6-я пара?» бот не давал.

Тот же `range(1, 6)` стоял ещё в двух клавиатурах редактора
(`paras_kb`, `sub_slots_kb`): староста не мог править шестую пару.
"""
import datetime

from common.schedule import MAX_PARA, format_bell
from infrastructure.database.models import BellSchedule
from tgbot.handlers import editor


def bell(para, hour, group="I_IV", day_type="OTHER"):
    return BellSchedule(day_type=day_type, course_group=group, para=para,
                        start=datetime.time(hour, 0),
                        h1_end=datetime.time(hour, 45),
                        h2_start=datetime.time(hour + 1, 0),
                        end=datetime.time(hour + 1, 40))


def test_max_para_is_six():
    """Одна константа вместо трёх копий числа."""
    assert MAX_PARA == 6


def test_bell_grid_shows_sixth_para():
    """Главное: шестая пара попадает в вывод.

    Без правки строка обрезалась, хотя звонок для неё в базе есть.
    """
    grid = {(b.day_type, b.course_group, b.para): b
            for b in (bell(p, 8 + p) for p in range(1, MAX_PARA + 1))}

    text = format_bell(grid, {})
    assert "6 пара" in text, "шестая пара не попала в сетку звонков"


def test_bell_grid_still_shows_first_five():
    """Расширение не сломало остальное."""
    grid = {(b.day_type, b.course_group, b.para): b
            for b in (bell(p, 8 + p) for p in range(1, MAX_PARA + 1))}

    text = format_bell(grid, {})
    for p in range(1, 7):
        assert f"{p} пара" in text, f"пропала {p} пара"


def test_editor_paras_kb_has_six_rows():
    """Клавиатура редактора показывает все шесть пар."""
    kb = editor.paras_kb(1, "ANY", [])
    assert len(kb.inline_keyboard) >= MAX_PARA, (
        f"строк в клавиатуре {len(kb.inline_keyboard)}, ожидали ≥{MAX_PARA}"
    )


def test_editor_sub_slots_kb_has_six_rows():
    """И клавиатура замен тоже."""
    kb = editor.sub_slots_kb("2026-10-27", [], {})
    assert len(kb.inline_keyboard) >= MAX_PARA


def test_no_hardcoded_range_left():
    """Третьей копии числа не осталось (в коде, не в комментариях)."""
    import inspect
    from common import schedule

    for mod in (schedule, editor):
        src = inspect.getsource(mod)
        for line in src.splitlines():
            code = line.split("#", 1)[0]
            assert "range(1, 6)" not in code, f"остался range(1, 6) в {mod.__name__}"
