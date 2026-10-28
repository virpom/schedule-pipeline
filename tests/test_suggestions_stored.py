"""Подсказки предметов в базовом расписании сохраняются в FSM (073 / 144).

cb_edit_base строил список и рисовал кнопки, но не клал его в state.
В callback_data лежит индекс, а cb_subject_suggestion достаёт список из
FSM — получал пустоту и отвечал «Устарело» на любую кнопку.

Путь замен (ed:ssug) был в порядке: там update_data(suggestions=...) есть.
Тест держит оба пути, чтобы второй не сломали, чиня первый.
"""
import inspect

from tgbot.handlers import editor


def _src(fn) -> str:
    return inspect.getsource(fn)


def test_base_stores_suggestions():
    body = _src(editor.cb_edit_base)
    assert "suggestions=suggestions" in body, "список не кладётся в state"


def test_sub_still_stores_suggestions():
    """Регрессия: путь замен был исправен."""
    body = _src(editor.cb_sub_edit)
    assert "suggestions=suggestions" in body


def test_both_paths_share_handler():
    """Один обработчик на обе кнопки — значит формат state обязан совпадать."""
    assert "ed:sug:" in _src(editor.cb_edit_base)
    assert "ed:ssug:" in _src(editor.cb_sub_edit)


def test_index_matches_state_list():
    """В кнопке индекс, в state — список: длины должны совпадать."""
    body = _src(editor._suggest_kb)
    assert "enumerate(items" in body
    assert "cb_prefix}:{i}" in body
