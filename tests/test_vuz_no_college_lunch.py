"""Обед колледжа не попадает в сетку вуза.

План 007. `course_group_from_group` для группы вуза возвращает `VUZ`,
а строк с `course_group='VUZ'` в `bell_lunch` ноль. Поэтому срабатывала
запасная ветка `or lunches.get((dt, "I_IV"))` — обед колледжа первого
курса.

Воспроизведено: вузовская 2-я пара 10:20–11:05 / 11:15–11:50, обед
I_IV лежит на паре 2 с 11:30 по 11:55. Студент видел

    10:20–11:05 / 🍽 11:30–11:55 / 11:15–11:50

то есть время шло не по порядку: 11:05 -> 11:30 -> 11:15.

Запасная ветка нужна колледжу: при неопределённом курсе `cg` бывает
None, и I_IV служит разумным умолчанием. Для вуза умолчание неверно —
своего обеда у него нет вообще.
"""
import datetime

from common.schedule import (DETAIL_FULL, VUZ_GROUP, course_group_from_group,
                             format_day)
from tgbot.services.schedule_layer import Slot

T = datetime.time


class _BS:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _bell(start, end, h1, h2):
    return _BS(start=start, end=end, h1_end=h1, h2_start=h2)


def _lunch(start, end, para):
    return _BS(lunch_start=start, lunch_end=end, para=para, position="inside")


VUZ_BELL = {("OTHER", VUZ_GROUP, 2): _bell(T(10, 20), T(11, 50), T(11, 5), T(11, 15))}
COLLEGE_BELL = {("OTHER", "I_IV", 2): _bell(T(9, 0), T(10, 35), T(9, 45), T(9, 50))}
LUNCHES = {("OTHER", "I_IV"): _lunch(T(11, 30), T(11, 55), 2)}
DATE = datetime.date(2026, 10, 27)


def _line(lesson, bell, detail=DETAIL_FULL):
    out = format_day(DATE, [lesson], bell, LUNCHES, detail)
    return next(l for l in out.split("\n") if l.strip().startswith(("1)", "2)", "3)")))


def test_course_group_for_vuz_is_vuz():
    """Предпосылка дефекта: у вуза cg == VUZ."""
    assert course_group_from_group("ГД-26@vuz") == VUZ_GROUP


def test_vuz_has_no_college_lunch():
    """Главное: обед колледжа не влезает в пару вуза."""
    v = Slot(2, "Математический анализ (прак)", "Иванов И.И.", group="ГД-26@vuz")
    line = _line(v, VUZ_BELL)
    assert "🍽" not in line, f"обед колледжа в вузе: {line}"


def test_vuz_time_is_ordered():
    """Время внутри пары идёт по возрастанию."""
    v = Slot(2, "Мат. анализ", "Иванов И.И.", group="ГД-26@vuz")
    line = _line(v, VUZ_BELL)
    times = [t for t in line.split("</b>")[0].replace("<b>", "").split()
             if "–" in t]
    starts = [t.split("–")[0] for t in times]
    assert starts == sorted(starts), f"время не по порядку: {line}"


def test_college_keeps_its_lunch():
    """Колледж не должен потерять свой обед вместе с вузовским багом."""
    k = Slot(2, "Мат. анализ", "Иванов И.И.", group="ДП-26")
    line = _line(k, COLLEGE_BELL)
    assert "🍽" in line, f"обед колледжа пропал: {line}"


def test_bell_lunch_guard_present():
    """Напоминания о звонках тоже не должны присылать обед вузу."""
    import inspect

    from tgbot.services import bell

    src = inspect.getsource(bell._tick)
    blocks = src.split("lunches.get((dt, cg))")
    assert len(blocks) >= 2
    assert "cg != VUZ_GROUP" in src, "нет защиты в bell.py"


def test_schedule_lunch_guard_present():
    import inspect

    from common import schedule

    src = inspect.getsource(schedule.format_day)
    assert "cg != VUZ_GROUP" in src, "нет защиты в format_day"
