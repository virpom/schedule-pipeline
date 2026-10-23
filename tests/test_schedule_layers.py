"""Тесты слоёв расписания: чётность недели и наложение замен."""
import datetime

from common.schedule import (
    PARITY_EVEN,
    PARITY_ODD,
    SUB_ADD,
    SUB_CANCEL,
    SUB_REPLACE,
    merge_day,
    week_parity,
)


class Slot:
    def __init__(self, para, subject, teacher="", room="", action=None):
        self.para = para
        self.subject = subject
        self.teacher = teacher
        self.room = room
        self.action = action


def test_week_parity_iso():
    # ISO-недели 42 (чётная) и 43 (нечётная) — сверено с календарём 2026
    assert week_parity(datetime.date(2026, 10, 16)) == PARITY_EVEN   # пт, нед. 42
    assert week_parity(datetime.date(2026, 10, 19)) == PARITY_ODD    # пн, нед. 43
    assert week_parity(datetime.date(2026, 10, 26)) == PARITY_EVEN   # пн, нед. 44


def test_week_parity_offset():
    d = datetime.date(2026, 10, 16)
    assert week_parity(d, parity_offset=1) == PARITY_ODD


def test_merge_no_subs_returns_base_sorted():
    base = [Slot(3, "Физика"), Slot(1, "Математика")]
    result = merge_day(base, [])
    assert [l.para for l in result] == [1, 3]


def test_merge_replace_overrides_base():
    base = [Slot(1, "Математика"), Slot(2, "Физика")]
    subs = [Slot(2, "Химия", action=SUB_REPLACE)]
    result = merge_day(base, subs)
    assert [l.subject for l in result] == ["Математика", "Химия"]


def test_merge_cancel_removes_slot():
    base = [Slot(1, "Математика"), Slot(2, "Физика")]
    subs = [Slot(1, "", action=SUB_CANCEL)]
    result = merge_day(base, subs)
    assert [l.para for l in result] == [2]


def test_merge_add_inserts_new_slot():
    base = [Slot(1, "Математика")]
    subs = [Slot(4, "Физкультура", action=SUB_ADD)]
    result = merge_day(base, subs)
    assert [l.para for l in result] == [1, 4]


def test_merge_cancel_all_gives_empty_day():
    base = [Slot(1, "Математика"), Slot(2, "Физика")]
    subs = [Slot(1, "", action=SUB_CANCEL), Slot(2, "", action=SUB_CANCEL)]
    assert merge_day(base, subs) == []


def test_merge_cancel_then_add_same_slot():
    """Отменили, потом добавили другой предмет в тот же слот."""
    base = [Slot(2, "Физика")]
    subs = [Slot(2, "", action=SUB_CANCEL), Slot(2, "История", action=SUB_ADD)]
    result = merge_day(base, subs)
    assert [l.subject for l in result] == ["История"]


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok  {name}")
    print("OK")
