"""Отзыв прав посреди ввода не оставляет старосту в тишине.

План 131, сценарий 2. `_save_base` и `_save_sub` начинались с

    group = await editor_group(repo, event.from_user.id)
    if not group:
        return

Если права отозвали, пока староста вводил предмет, фамилию и кабинет,
он проходил все три шага и на последнем не получал ничего: ни ошибки,
ни подтверждения, ни сообщения. Диалог просто заканчивался.

Сценарий 1 из плана (рестарт) править не нужно: `MemoryStorage` чистит
и состояние, и данные одновременно, поэтому `on_subject` без состояния
не вызывается, а текст уходит в `any_text` с меню.
"""
import inspect

import pytest

from tgbot.handlers import editor


def _body(fn) -> str:
    return inspect.getsource(fn)


@pytest.mark.parametrize("fn", [editor._save_base, editor._save_sub])
def test_save_reports_revoked_rights(fn):
    src = _body(fn)
    head = src[:src.index("weekday =") if "weekday =" in src else src.index("date =")]
    assert "Права редактора отозваны" in head, f"{fn.__name__} молчит при отзыве прав"


@pytest.mark.parametrize("fn", [editor._save_base, editor._save_sub])
def test_save_clears_state_on_revoked(fn):
    src = _body(fn)
    head = src[:src.index("weekday =") if "weekday =" in src else src.index("date =")]
    assert "state.clear()" in head, f"{fn.__name__} оставляет диалог висеть"


@pytest.mark.parametrize("fn", [editor._save_base, editor._save_sub])
def test_save_answers_both_entry_points(fn):
    """event бывает и Message, и CallbackQuery — сообщение нужно обоим."""
    src = _body(fn)
    head = src[:src.index("weekday =") if "weekday =" in src else src.index("date =")]
    assert "if via_cb:" in head, "не различает колбэк и сообщение"
    assert "event.message.edit_text" in head, "колбэк остаётся без ответа"
    assert "event.answer(text" in head, "сообщение остаётся без ответа"


@pytest.mark.parametrize("fn", [editor._save_base, editor._save_sub])
def test_no_bare_return_on_missing_group(fn):
    """Голого `if not group: return` быть не должно."""
    src = _body(fn)
    assert "if not group:\n        return" not in src, f"{fn.__name__} молча выходит"


def test_message_handler_reports_no_rights():
    """Вход в редактор тоже объясняет отказ."""
    src = _body(editor.editor_entry)
    assert "нет прав редактора" in src


def test_no_rights_kb_exists():
    assert callable(editor._no_rights_kb)
