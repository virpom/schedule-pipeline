"""Тесты чётности недели.

``merge_day`` удалён: в проде его заменил ``schedule_layer.get_day_slots()``,
а слияние слоёв покрыто ``test_schedule_layer_service.py`` на реальном repo.
"""
import datetime

from common.schedule import PARITY_EVEN, PARITY_ODD, week_parity


def test_week_parity_iso():
    # ISO-недели 42 (чётная) и 43 (нечётная) — сверено с календарём 2026
    assert week_parity(datetime.date(2026, 10, 16)) == PARITY_EVEN   # пт, нед. 42
    assert week_parity(datetime.date(2026, 10, 19)) == PARITY_ODD    # пн, нед. 43
    assert week_parity(datetime.date(2026, 10, 26)) == PARITY_EVEN   # пн, нед. 44


def test_week_parity_offset():
    d = datetime.date(2026, 10, 16)
    assert week_parity(d, parity_offset=1) == PARITY_ODD


def test_college_parity_is_iso_shifted():
    """Сдвиг колледжа переворачивает чётность на всех датах."""
    from tgbot.services.schedule_layer import PARITY_OFFSET

    for day in range(1, 29):
        d = datetime.date(2026, 10, day)
        assert week_parity(d, PARITY_OFFSET) != week_parity(d)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok  {name}")
    print("OK")
