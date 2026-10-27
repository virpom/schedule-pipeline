"""Пропавший файл фото не убивает рассылку.

План 132. `FSInputFile` открывает файл лениво, внутри `send_photo`.
`FileNotFoundError` и `PermissionError` не подклассы TelegramAPIError,
поэтому пролетали мимо всех четырёх `except`. Исключение выходило в
`broadcast_schedule`, где цикл не был обёрнут в try — и вместо одного
получателя расписание не получали все оставшиеся.

Окно: `random_photo` отдаёт путь, существовавший в момент листинга, а
рассылка идёт ~6 секунд. Удаление файла в этом окне ломало очередь.
"""
import inspect
import logging

import pytest

from tgbot.services import broadcaster


class _Bot:
    """Бот, который, как и настоящий FSInputFile, читает файл при отправке."""

    def __init__(self, exc=None):
        self.exc = exc
        self.calls = []

    async def send_photo(self, user_id, photo, caption=""):
        self.calls.append(user_id)
        if self.exc:
            raise self.exc
        # Настоящий aiogram открывает файл здесь, а не в конструкторе.
        if isinstance(photo, str):
            path = photo
        elif hasattr(photo, "path"):
            path = photo.path
        else:
            return None
        with open(path, "rb") as f:
            f.read(1)
        return None

    async def send_message(self, user_id, text, **kw):
        self.calls.append(user_id)
        if self.exc:
            raise self.exc
        return None


@pytest.fixture(autouse=True)
def _clean():
    broadcaster._file_ids.clear()
    yield
    broadcaster._file_ids.clear()


@pytest.mark.asyncio
async def test_missing_file_returns_false(tmp_path):
    """Файла нет — send_photo возвращает False, а не падает."""
    missing = str(tmp_path / "nope.jpg")
    ok = await broadcaster.send_photo(_Bot(), 1, missing)
    assert ok is False


@pytest.mark.asyncio
async def test_permission_error_returns_false(tmp_path):
    """PermissionError — тоже OSError, тоже не должен пролетать."""
    import os

    photo = tmp_path / "p.jpg"
    photo.write_bytes(b"x")
    os.chmod(photo, 0o000)
    try:
        ok = await broadcaster.send_photo(_Bot(), 1, str(photo))
    finally:
        os.chmod(photo, 0o600)
    assert ok is False


@pytest.mark.asyncio
async def test_broadcast_survives_missing_photo(tmp_path):
    """Первый получатель с битым фото не лишает остальных сообщения."""
    bad = str(tmp_path / "gone.jpg")
    bot = _Bot()
    items = [(1, "текст раз", bad), (2, "текст два", None), (3, "текст три", None)]
    sent = await broadcaster.broadcast_schedule(bot, items, rate=1000.0)
    assert 2 in bot.calls and 3 in bot.calls, "дошли не до всех"
    assert sent >= 2


@pytest.mark.asyncio
async def test_broadcast_survives_unexpected_exception():
    """Любое неожиданное исключение на одном получателе не рвёт очередь."""
    bot = _Bot(exc=RuntimeError("что-то новое"))
    items = [(1, "а", None), (2, "б", None)]
    sent = await broadcaster.broadcast_schedule(bot, items, rate=1000.0)
    # Первый проход должен дойти до обоих: с плана 017 неудачники
    # повторяются отдельным проходом, поэтому вызовов может быть больше.
    assert bot.calls[:2] == [1, 2], f"цикл оборвался: {bot.calls}"
    assert sent == 0


@pytest.mark.asyncio
async def test_broadcast_many_survives_exception():
    bot = _Bot(exc=RuntimeError("сбой"))
    sent = await broadcaster.broadcast_many(bot, [(1, "а"), (2, "б")], rate=1000.0)
    assert bot.calls[:2] == [1, 2], f"цикл оборвался: {bot.calls}"
    assert sent == 0


def test_oserror_branch_present():
    src = inspect.getsource(broadcaster.send_photo)
    assert "OSError" in src, "нет обработки OSError"
    # именно в send_photo, а не в соседней функции
    assert src.count("except OSError") == 1


def test_oserror_logs_not_raises(caplog):
    """Ошибка логируется, а не глотается молча."""
    import asyncio

    async def run():
        with caplog.at_level(logging.ERROR):
            return await broadcaster.send_photo(_Bot(), 7, "/нет/такого.jpg")

    assert asyncio.run(run()) is False
