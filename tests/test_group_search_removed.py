"""Поиск группы удалён, а не оставлен мёртвым (план 059).

`cb_find_group` слушал `find_group`, но ни одна кнопка этот callback
не шлёт — 42 строки не выполнялись никогда. Занимали имя состояния
рядом с рабочими `SubjectSearch` и `TeacherSearch`, из-за чего
читающий код решал, что поиск группы работает.

Группа меняется двумя путями: кнопками «Где ты учишься?» ->
`unit:college` -> `group:XXX` и командой `/group`. Третьего нет.

Если поиск группы понадобится — сначала кнопка, потом обработчик,
а не наоборот.
"""
import subprocess

from tgbot.handlers import user


def test_state_group_removed():
    assert not hasattr(user, "GroupSearch")


def test_handlers_removed():
    assert not hasattr(user, "cb_find_group")
    assert not hasattr(user, "group_answer")


def test_no_find_group_callback():
    """Ни одной ссылки на callback в коде, кроме тестов."""
    out = subprocess.run(
        ["grep", "-rn", "find_group", "--include=*.py", "tgbot/", "infrastructure/", "common/"],
        capture_output=True, text=True,
    )
    assert out.stdout.strip() == "", f"остались ссылки:\n{out.stdout}"


def test_working_searches_intact():
    """Соседние поиски, у которых кнопки есть, не задеты."""
    assert hasattr(user, "SubjectSearch")
    assert hasattr(user, "TeacherSearch")
    assert hasattr(user, "teacher_answer")
    body = open("tgbot/handlers/user.py").read()
    assert 'callback_data="find"' in body
    assert 'callback_data="find_teacher"' in body


def test_group_change_paths_still_exist():
    """Удаление не задело реальные способы сменить группу."""
    body = open("tgbot/handlers/user.py").read()
    assert "group:" in body or "group_cb" in body or "unit:college" in body
    assert "set_group_cmd" in body
