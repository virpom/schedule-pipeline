"""Фото не перезагружается в Telegram на каждую отправку.

План 043. `send_photo` каждый раз читал файл с диска через FSInputFile
и загружал его заново. При 14 датах это 196 загрузок по 390 КБ вместо
одной. file_id, который Telegram возвращает в ответе, нигде не хранился.

Заодно — одно фото на день для всех. `random_photo` звался на каждого
подписчика и делал os.listdir: 3080 чтений диска при 14 датах.
"""
import inspect
import pathlib

import pytest
from aiogram.exceptions import TelegramBadRequest

from tgbot.services import broadcaster, poller


class _Msg:
    def __init__(self, file_id):
        self.photo = [type("P", (), {"file_id": file_id + "_small"})(),
                      type("P", (), {"file_id": file_id})()]


class _Bot:
    def __init__(self, fail_id=False, file_id="FID1"):
        self.fail_id = fail_id
        self.file_id = file_id
        self.calls = []

    async def send_photo(self, user_id, photo, caption=""):
        self.calls.append(photo)
        if isinstance(photo, str):
            if self.fail_id:
                self.fail_id = False   # протухает один раз
                raise TelegramBadRequest(method=None, message="wrong file_id")
            return _Msg(photo)
        return _Msg(self.file_id)


@pytest.fixture(autouse=True)
def _clean_cache():
    broadcaster._file_ids.clear()
    yield
    broadcaster._file_ids.clear()


@pytest.mark.asyncio
async def test_second_send_uses_file_id(tmp_path):
    """Второй раз уходит file_id, а не FSInputFile."""
    photo = tmp_path / "p.jpg"
    photo.write_bytes(b"x")
    bot = _Bot()

    await broadcaster.send_photo(bot, 1, str(photo))
    assert not isinstance(bot.calls[0], str), "первый раз должен грузить файл"

    await broadcaster.send_photo(bot, 2, str(photo))
    assert bot.calls[1] == "FID1", "второй раз должен идти по file_id"


@pytest.mark.asyncio
async def test_cache_keyed_by_path(tmp_path):
    a = tmp_path / "a.jpg"
    b = tmp_path / "b.jpg"
    a.write_bytes(b"x")
    b.write_bytes(b"y")
    bot = _Bot()
    await broadcaster.send_photo(bot, 1, str(a))
    await broadcaster.send_photo(bot, 2, str(b))
    assert len(broadcaster._file_ids) == 2


@pytest.mark.asyncio
async def test_expired_file_id_falls_back(tmp_path):
    """Протухший file_id не ломает отправку навсегда."""
    photo = tmp_path / "p.jpg"
    photo.write_bytes(b"x")
    bot = _Bot()
    await broadcaster.send_photo(bot, 1, str(photo))

    bot.fail_id = True
    await broadcaster.send_photo(bot, 2, str(photo))
    # упало на file_id, затем перезагрузили файлом
    assert not isinstance(bot.calls[2], str), "нет повтора с файлом"


@pytest.mark.asyncio
async def test_expired_file_id_refreshed(tmp_path):
    """После протухания кэш обновляется, а не остаётся битым."""
    photo = tmp_path / "p.jpg"
    photo.write_bytes(b"x")
    bot = _Bot()
    await broadcaster.send_photo(bot, 1, str(photo))
    bot.fail_id = True
    bot.file_id = "FID2"
    await broadcaster.send_photo(bot, 2, str(photo))
    assert broadcaster._file_ids[str(photo)] == "FID2"


def test_random_photo_called_once_per_day():
    """`random_photo` поднят на уровень даты, а не пользователя."""
    src = inspect.getsource(poller.notify_new_schedule) \
        if hasattr(poller, "notify_new_schedule") else ""
    if not src:
        # функция может называться иначе — ищем по файлу
        src = pathlib.Path(poller.__file__).read_text()
    code = "\n".join(line.split("#", 1)[0] for line in src.splitlines())
    assert code.count("random_photo(") == 1, \
        "random_photo зовётся чаще одного раза на дату"


def test_day_photo_used_for_users():
    src = pathlib.Path(poller.__file__).read_text()
    assert "day_photo if (user.send_image" in src
