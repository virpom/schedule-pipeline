"""Откат отвечает на callback ровно один раз (ранг 74).

cb_undo зовёт cb.answer(msg, show_alert=True), а сразу за ним cb_log,
который заканчивался вторым cb.answer(). Telegram отвечает на второй
вызов 400-й ошибкой «query is too old / query ID is invalid» — она
сыпалась в лог после каждого отката.
"""
import inspect

from tgbot.handlers import editor


def _src(fn) -> str:
    return inspect.getsource(fn)


def test_log_has_notify_flag():
    sig = inspect.signature(editor.cb_log)
    assert "notify" in sig.parameters
    assert sig.parameters["notify"].default is True, \
        "по умолчанию должен отвечать: кнопку зовут из меню"


def _run_log(notify: bool) -> list:
    """Настоящий cb_log: сколько раз ответил на callback."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    answered = []

    class _Log:
        @staticmethod
        async def get_recent(group, limit=10):
            return []

    class _Editors:
        @staticmethod
        async def get_group_for(uid):
            return "ДП-26"

    class _Repo:
        edit_log = _Log()
        editors = _Editors()

    async def scenario():
        cb = MagicMock()
        cb.from_user.id = 1
        cb.message = MagicMock()
        cb.message.edit_text = AsyncMock()

        async def answer(text=None, show_alert=False):
            answered.append(text)

        cb.answer = answer
        state = MagicMock()
        state.clear = AsyncMock()
        await editor.cb_log(cb, _Repo(), state, notify=notify)

    asyncio.run(scenario())
    return answered


def test_log_answers_when_notified():
    assert len(_run_log(True)) == 1


def test_log_silent_when_not_notified():
    """Иначе cb_undo отвечает дважды — Telegram даёт 400."""
    assert _run_log(False) == []


def test_undo_calls_log_without_notify():
    body = _src(editor.cb_undo)
    assert "cb_log(cb, repo, notify=False)" in body, \
        "cb_undo ответит дважды"


def test_undo_answers_exactly_once():
    """Гоняем настоящий cb_undo: считаем вызовы cb.answer."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    answered = []

    class _Log:
        @staticmethod
        async def get_last(group, user_id=None):
            e = MagicMock()
            e.id = 1
            e.layer = "base"
            e.action = "add"
            e.date = None
            e.para = 3
            e.old_value = "{}"
            e.new_value = '{"weekday": 1, "parity": "ODD"}'
            return e

        @staticmethod
        async def delete(edit_id):
            pass

        @staticmethod
        async def get_recent(group, limit=10):
            return []

    class _Editors:
        @staticmethod
        async def get_group_for(uid):
            return "ДП-26"

    class _Base:
        @staticmethod
        async def delete_slot(*a, **kw):
            pass

    class _Repo:
        edit_log = _Log()
        editors = _Editors()
        base_lessons = _Base()

    async def scenario():
        cb = MagicMock()
        cb.from_user.id = 1
        cb.data = "ed:undo"

        async def answer(text=None, show_alert=False):
            answered.append(text)

        cb.answer = answer
        cb.message = MagicMock()
        cb.message.edit_text = AsyncMock()
        # _rebuild дергает материализацию — подменяем
        orig = editor._rebuild
        editor._rebuild = AsyncMock(return_value=True)
        try:
            await editor.cb_undo(cb, _Repo())
        finally:
            editor._rebuild = orig

    asyncio.run(scenario())
    assert len(answered) == 1, f"ответов на callback: {len(answered)}"


def test_log_works_without_state():
    """cb_undo не передаёт state — None не должен ронять."""
    body = _src(editor.cb_log)
    assert "if state is not None:" in body


def test_state_optional_in_signature():
    sig = inspect.signature(editor.cb_log)
    assert sig.parameters["state"].default is None
