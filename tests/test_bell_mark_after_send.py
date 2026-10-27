"""Звонок помечается отправленным ПОСЛЕ отправки.

План 109. Было: `mark_sent` коммитила, потом `send_message`. При
`TelegramForbiddenError` (человек заблокировал бота) отправка
возвращала `False`, но её никто не смотрел — отметка уже стояла, и
повтора не будет. Напоминание терялось навсегда.

Та же ловушка, что в плане 050 для тревог админу.
"""
import inspect

from tgbot.services import bell


def test_mark_sent_after_send():
    """В исходнике `send_message` идёт раньше `mark_sent`."""
    src = inspect.getsource(bell._tick)
    code = "\n".join(line.split("#", 1)[0] for line in src.splitlines())
    send = code.find("send_message")
    mark = code.find("mark_sent(")
    assert send != -1 and mark != -1
    assert send < mark, "mark_sent вызывается до отправки — звонок потеряется"


def test_send_result_is_checked():
    """Результат `send_message` не отбрасывается."""
    src = inspect.getsource(bell._tick)
    code = "\n".join(line.split("#", 1)[0] for line in src.splitlines())
    assert "if not await send_message" in code, \
        "False от send_message игнорируется"


def test_no_mark_before_send_on_failure():
    """При неудаче до `mark_sent` не доходит — есть `continue`."""
    src = inspect.getsource(bell._tick)
    code = "\n".join(line.split("#", 1)[0] for line in src.splitlines())
    guard = code.split("send_message")[1].split("mark_sent")[0]
    assert "continue" in guard, "нет раннего выхода при неудачной отправке"
