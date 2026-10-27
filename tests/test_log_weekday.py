"""Журнал правок различает дни недели (план 063).

У правок базы даты нет — она повторяется каждую неделю, — поэтому
журнал печатал «база/3 пара» для всех сразу. Три правки (пн, ср, пт,
все третьи пары) давали три неразличимые строки, и староста не мог
понять, какую откатывать. День недели и чётность уже лежали в
new_value: их пишет _save_base.
"""
import types

import pytest

from tgbot.handlers import editor


def _entry(**kw):
    base = dict(layer="base", para=3, date=None, action="edit",
                new_value=None, old_value=None, created_at=None)
    base.update(kw)
    return types.SimpleNamespace(**base)


def test_base_has_weekday_and_parity():
    e = _entry(new_value='{"weekday": 3, "parity": "EVEN"}')
    out = editor._log_place(e)
    assert "Ср" in out, out
    assert "чётная" in out, out
    assert "3 пара" in out, out


def test_different_days_differ():
    """Главное: строки разных дней не должны совпадать."""
    mon = editor._log_place(_entry(new_value='{"weekday": 1, "parity": "ODD"}'))
    wed = editor._log_place(_entry(new_value='{"weekday": 3, "parity": "EVEN"}'))
    fri = editor._log_place(_entry(new_value='{"weekday": 5, "parity": "ODD"}'))
    assert len({mon, wed, fri}) == 3, (mon, wed, fri)


def test_sub_has_date():
    import datetime
    e = _entry(layer="sub", date=datetime.date(2026, 10, 28))
    out = editor._log_place(e)
    assert "28.10" in out
    assert "замена" in out


def test_missing_weekday_shows_question():
    assert "?" in editor._log_place(_entry(new_value='{"parity": "ODD"}'))


def test_unknown_layer_not_empty():
    """Раньше where оставался пустым и строка начиналась с «· ·»."""
    out = editor._log_place(_entry(layer="weird", para=2))
    assert out.strip()
    assert "weird" in out


def test_broken_json_does_not_crash():
    assert editor._json("{не json") == {}
    assert editor._json("") == {}
    assert editor._json(None) == {}
    assert editor._json("[1,2]") == {}
    assert editor._json('{"a": 1}') == {"a": 1}


def test_log_screen_uses_place():
    import inspect
    assert "_log_place" in inspect.getsource(editor.cb_log)


def test_undo_survives_broken_json():
    """Битая строка журнала не должна ломать откат."""
    import inspect
    src = inspect.getsource(editor.cb_undo)
    assert "json.loads" not in src, "откат падает на битом JSON"
    assert "_json(" in src


@pytest.mark.parametrize("wd", [1, 2, 3, 4, 5, 6, 7])
def test_every_weekday_renders(wd):
    out = editor._log_place(_entry(new_value='{"weekday": %d, "parity": "ODD"}' % wd))
    assert "?" not in out, out
