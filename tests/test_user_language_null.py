"""Новый пользователь без language_code не должен ломать регистрацию.

Живой сбой на проде 27.10.2026 17:26:

```
sqlalchemy.exc.IntegrityError: (sqlite3.IntegrityError)
NOT NULL constraint failed: users.language
[parameters: (6236704873, 'timaaxaxa', 'Zayungx404', None, 'student', ...)]
```

`event.from_user.language_code` в Telegram необязателен и у части
клиентов приходит `None`. Middleware передавал его как есть, колонка
`users.language` — NOT NULL, и вставка падала. Человек просто не мог
начать пользоваться ботом: `/start` не отвечал ничем, кроме ошибки в
логе.
"""

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from infrastructure.database.models import Base
from infrastructure.database.repo.requests import RequestsRepo


@pytest.fixture
async def repo():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    pool = async_sessionmaker(engine, expire_on_commit=False)
    async with pool() as session:
        yield RequestsRepo(session)
    await engine.dispose()


@pytest.mark.asyncio
async def test_user_without_language_code_is_created(repo):
    """Главное: None в language_code не роняет вставку."""
    user = await repo.users.get_or_create_user(
        user_id=6236704873,
        full_name="Zayungx404",
        language=None,
        username="timaaxaxa",
    )
    assert user.id == 6236704873
    assert user.language == "ru", "подставился не русский по умолчанию"


@pytest.mark.asyncio
async def test_user_without_full_name_is_created(repo):
    """full_name тоже NOT NULL, а у аккаунтов без имени он пустой."""
    user = await repo.users.get_or_create_user(
        user_id=111,
        full_name="",
        language="ru",
        username=None,
    )
    assert user.id == 111
    assert user.full_name.strip(), "имя осталось пустым"


@pytest.mark.asyncio
async def test_user_with_none_full_name_is_created(repo):
    user = await repo.users.get_or_create_user(
        user_id=222,
        full_name=None,
        language=None,
        username=None,
    )
    assert user.id == 222
    assert user.full_name.strip()


@pytest.mark.asyncio
async def test_existing_user_still_updates(repo):
    """Повторный вход обновляет имя и не падает."""
    await repo.users.get_or_create_user(
        user_id=333, full_name="Старое", language="ru", username="old")
    user = await repo.users.get_or_create_user(
        user_id=333, full_name="Новое", language=None, username="new")
    assert user.full_name == "Новое"
    assert user.username == "new"


@pytest.mark.asyncio
async def test_language_is_kept_when_provided(repo):
    """Явный язык не перетирается дефолтом."""
    user = await repo.users.get_or_create_user(
        user_id=444, full_name="Тест", language="en", username=None)
    assert user.language == "en"


def test_middleware_substitutes_language():
    """Middleware подставляет 'ru' до вызова репозитория.

    Проверка исходником: сам middleware требует живого aiogram-события,
    а дефект ровно в одном выражении.
    """
    import inspect
    from tgbot.middlewares import database

    src = inspect.getsource(database)
    assert 'language_code or "ru"' in src, \
        "middleware снова передаёт language_code как есть"
