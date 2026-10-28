"""Поиск человека по имени для выдачи прав редактора (план 160).

SQLite ``lower()`` и ``LIKE`` понимают только ASCII: ``lower('Цатурян')``
не меняет ни одного символа, поэтому запрос «цатурян» не находил
«Цатурян Владислав». Админ вводил фамилию строчными и получал «никто не
найден». Плюс ``%`` без экранирования совпадал со всеми.

Поэтому ``UserRepo.search`` смотрит на SQL-функции через фейковую
сессию: если регистр снова начнут понижать в SQL, тест упадёт по
``NotImplementedError``, а не тихо пройдёт в зависимости от SQLite.
"""
import asyncio
import datetime

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
    """Отдаёт всех пользователей; любой SQL-фильтр — ошибка."""

    def __init__(self, users):
        self.users = users
        self.queries = 0

    async def execute(self, stmt):
        self.queries += 1
        if self.queries > 1:
            raise NotImplementedError(
                f"search полез в SQL с фильтром: {stmt}. SQLite не понижает "
                "регистр кириллицы — фильтровать надо в Python.")
        return FakeResult(self.users)


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _user(uid, username, full_name, seen):
    u = User()
    u.id = uid
    u.username = username
    u.full_name = full_name
    u.last_seen = seen
    return u


def _repo():
    return UserRepo(FakeSession([
        _user(1, "virp0m", "Цатурян Владислав", datetime.datetime(2026, 10, 1)),
        _user(2, "n42", "Найс Андрей", datetime.datetime(2026, 10, 2)),
        _user(3, "x", "сандорская ольга", datetime.datetime(2026, 10, 3)),
        _user(4, "y", "Руфат Дима", datetime.datetime(2026, 10, 4)),
    ]))


def _ids(query, limit=8):
    return [u.id for u in run(_repo().search(query, limit=limit))]


def test_cyrillic_lowercase_finds_capitalized():
    """Главный дефект: фамилия строчными не находила «Цатурян»."""
    assert _ids("цатурян") == [1]
    assert _ids("найс") == [2]
    assert _ids("руфат") == [4]


def test_given_name_matches_too():
    """Ищут и по имени, а не только по фамилии."""
    assert _ids("владислав") == [1]
    assert _ids("андрей") == [2]


def test_query_with_capital_finds_lowercase_stored():
    assert _ids("РУФАТ") == [4]
    assert _ids("Сандорская") == [3]


def test_username_and_id_still_work():
    assert _ids("@virp0m") == [1]
    assert _ids("VIRP0M") == [1]


def test_id_branch_untouched():
    repo = UserRepo(FakeSession([
        _user(7, "z", "Кто-то Там", None)]))
    # Голое число — это id: get() находит его точным запросом, а не по
    # подстроке «7» в имени (иначе «7» цепляло бы «Иванов 7 группа»).
    assert [u.id for u in run(repo.search("7"))] == [7]


def test_wildcards_are_literal_not_match_all():
    """`%` раньше давал LIKE '%%%' и возвращал всех подряд."""
    assert _ids("%") == []
    assert _ids("_") == []


def test_limit_and_freshness_order():
    assert _ids("а", limit=2) == [4, 3]


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok  {name}")
    print("OK")
