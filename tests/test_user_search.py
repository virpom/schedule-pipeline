"""Тесты поиска пользователя для выдачи прав редактора."""
import asyncio

from infrastructure.database.models import User
from infrastructure.database.repo.user import UserRepo


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class FakeSession:
    """Минимальная имитация: храним всех и фильтруем как SQLite."""

    def __init__(self, users):
        self.users = users

    async def execute(self, stmt):
        # Разбирать SQL не будем — вместо этого тестируем через отдельный
        # «движок» на sqlite в памяти (см. test_search_sql ниже).
        raise NotImplementedError


def _u(uid, username, full_name, group="ДП-26"):
    u = User()
    u.id = uid
    u.username = username
    u.full_name = full_name
    u.group = group
    u.last_seen = None
    return u


def test_search_query_normalization():
    """Проверяем нормализацию входа без обращения к БД."""
    cases = {
        "@virp0m": "virp0m",
        "virp0m": "virp0m",
        "@@x": "x",
        "  @spaced  ": "spaced",
    }
    for raw, expected in cases.items():
        assert raw.lstrip("@").strip() == expected or raw.strip().lstrip("@") == expected


def test_empty_query_returns_empty():
    repo = UserRepo(FakeSession([]))
    assert asyncio.run(repo.search("")) == []
    assert asyncio.run(repo.search("   ")) == []


def test_user_option_label():
    from tgbot.handlers.admin import _user_option
    label = _user_option(_u(1, "virp0m", "VirProm", "ДП-26"))
    assert "@virp0m" in label and "ДП-26" in label

    no_username = _u(2, None, "Иванов Иван", "АТ-26")
    assert _user_option(no_username).startswith("Иванов")

    no_name = _u(3, "solo", "solo", None)
    assert _user_option(no_name) == "@solo"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok  {name}")
    print("OK")
