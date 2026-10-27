"""Пересборка одного дня должна отмечать его опубликованным.

План 025. `materialize` (полный проход по 14 дням) писал признак
публикации в `schedule_file`, а `materialize_day` — нет. Обе собирают
одни и те же строки, но одна отмечала день, другая нет.

Сценарий поломки: староста ставит замену на день за пределами окна
материализации, `_rebuild(date=...)` вызывает `materialize_day`, строки
записаны, признака нет. Пар в этот день нет — и студент видит
«Расписание ещё не выложено» вместо «занятий нет», хотя замены учтены.
"""
import datetime
import inspect

import pytest

from tgbot.services import sync_eios


def test_materialize_day_publishes_the_day():
    """Главное: `materialize_day` вызывает `_publish_day`.

    Проверка исходником: сама функция требует живых репозиториев, а
    дефект ровно в отсутствующем вызове.
    """
    src = inspect.getsource(sync_eios.materialize_day)
    assert "_publish_day(repo, date)" in src, \
        "materialize_day не отмечает день опубликованным"


def test_materialize_uses_shared_helper():
    """Полный проход тоже через общую функцию, а не своей копией."""
    src = inspect.getsource(sync_eios.materialize)
    assert "_publish_day(repo, date)" in src
    assert "schedule_files.set_hash" not in src, \
        "в materialize осталась своя копия записи признака"


def test_publish_day_does_not_overwrite():
    """Существующий признак не перетирается.

    `set_hash` мог бы затереть настоящий хеш файла — день, пришедший с
    сайта, не должен выглядеть как «eios-<дата>».
    """
    src = inspect.getsource(sync_eios._publish_day)
    assert "get_hash(date) is None" in src, \
        "признак перетирается без проверки"


class FakeFiles:
    def __init__(self, existing=None):
        self.existing = existing
        self.written = []

    async def get_hash(self, date):
        return self.existing

    async def set_hash(self, date, value):
        self.written.append((date, value))


class FakeRepo:
    def __init__(self, existing=None):
        self.schedule_files = FakeFiles(existing)


@pytest.mark.asyncio
async def test_publish_day_writes_when_absent():
    repo = FakeRepo(existing=None)
    date = datetime.date(2026, 11, 15)
    await sync_eios._publish_day(repo, date)
    assert repo.schedule_files.written == [(date, "eios-2026-11-15")]


@pytest.mark.asyncio
async def test_publish_day_keeps_existing():
    repo = FakeRepo(existing="abc123")
    await sync_eios._publish_day(repo, datetime.date(2026, 11, 15))
    assert not repo.schedule_files.written, "перетёрли настоящий хеш"
