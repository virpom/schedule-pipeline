"""`/setnight` не должен принимать время с часовым поясом.

План 087. `time.fromisoformat` принимает «23:00+03:00» — aware-время.
`_in_night` сравнивал его с naive `now`, получал TypeError, поллер ловил
его общим except и молча перестал опрашивать сайт. Расписание замирало
до тех пор, пока админ не вспомнит про /setnight.
"""
import datetime as dt

from tgbot.handlers.admin import _parse_hhmm
from tgbot.services.poller import _in_night


def test_accepts_plain_hhmm():
    assert _parse_hhmm("23:00") == dt.time(23, 0)
    assert _parse_hhmm("07:00") == dt.time(7, 0)
    assert _parse_hhmm("00:00") == dt.time(0, 0)


def test_rejects_aware_time():
    """Главный случай: часовой пояс ломал поллер.

    Проверяем и то, что получилось бы без валидации — иначе тест не
    докажет, что дыра была настоящей.
    """
    assert _parse_hhmm("23:00+03:00") is None
    assert _parse_hhmm("07:00-05:00") is None

    # Без валидации fromisoformat действительно даёт aware-время,
    # и сравнение падает.
    aware = dt.time.fromisoformat("23:00+03:00")
    assert aware.tzinfo is not None
    try:
        aware < dt.time(7, 0)
    except TypeError:
        pass
    else:
        raise AssertionError("ожидали TypeError при сравнении aware с naive")


def test_rejects_seconds_and_short_forms():
    """`fromisoformat` принимает «23» и «07:00:00» — отбиваем оба.

    «07:00:00» даёт time(7, 0) с нулевыми секундами, поэтому по полям
    его от «07:00» не отличить: проверять надо строку.
    """
    for value in ("23", "07:00:00", "23:00:00.5", "7:00", "25:00", "99:99", ""):
        assert _parse_hhmm(value) is None, f"{value!r} не должен приниматься"


def test_in_night_survives_aware_value_in_db():
    """Защита в `_in_night`: кривое значение из БД не роняет поллер.

    Оно могло попасть туда до правки /setnight. Лучше тихо выключить
    ночную паузу, чем остановить опрос совсем.
    """
    now = dt.datetime(2026, 10, 27, 2, 0)
    assert _in_night(now, "23:00", "07:00") is True
    assert _in_night(now, "23:00+03:00", "07:00") is False
    assert _in_night(now, "23:00", "07:00+03:00") is False


def test_in_night_unchanged_for_normal_values():
    """Обычные значения работают как раньше."""
    night = dt.datetime(2026, 10, 27, 2, 0)
    day = dt.datetime(2026, 10, 27, 12, 0)
    assert _in_night(night, "23:00", "07:00") is True
    assert _in_night(day, "23:00", "07:00") is False
    assert _in_night(night, "", "") is False
    assert _in_night(night, "23:00", "23:00") is False
    # Пауза внутри дня.
    assert _in_night(day, "12:00", "13:00") is True
