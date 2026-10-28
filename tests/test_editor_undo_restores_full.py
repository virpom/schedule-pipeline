"""Откат удаления возвращает пару целиком (план 112).

cb_del_base писал в журнал только subject (teacher и room терялись), а
cb_undo брал weekday/parity из new_value — при удалении он пустой.
Откат молча ничего не делал и отвечал «Возвращено».

Для вузовской пары был ещё один слой: weeks — часть ключа строки, и без
неё upsert создавал строку с weeks='' рядом с исходной.
"""
import inspect
import json

from tgbot.handlers import editor


def test_delete_logs_teacher_room_weeks():
    src = inspect.getsource(editor.cb_del_base)
    for field in ("teacher", "room", "weeks", "weekday", "parity"):
        assert f'"{field}"' in src, f"в журнал не пишется {field}"


def test_undo_falls_back_to_old_for_weekday():
    src = inspect.getsource(editor.cb_undo)
    assert 'new.get("weekday") or old.get("weekday")' in src
    assert 'new.get("parity") or old.get("parity")' in src


def test_undo_passes_teacher_room_weeks():
    src = inspect.getsource(editor.cb_undo)
    assert 'old.get("teacher"' in src
    assert 'old.get("room"' in src
    assert 'old.get("weeks"' in src


def test_logged_value_shape():
    """Форма old_value, которую пишет удаление и читает откат."""
    src = inspect.getsource(editor.cb_del_base)
    line = [l for l in src.split("\n") if '"subject": old_slot.subject' in l][0]
    assert "old_slot.teacher" in src and "old_slot.room" in src
    assert "weeks" in src
    assert json.dumps({"subject": "X", "teacher": "Y", "room": "Z",
                       "weeks": "1,3", "weekday": 2, "parity": "ODD"})
