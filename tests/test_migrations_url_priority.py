"""URL миграций: переданный вызывающим главнее угаданного (план 124).

env.py на уровне модуля вызывает set_main_option, и это выглядело как
перезапись URL от migrations_runner. На деле _database_url() сначала
возвращает уже установленный URL — тот самый, что поставил runner, —
и только потом смотрит ALEMBIC_DB_URL и .env.

Тест держит этот порядок: если кто-то уберёт первую ветку, миграции
начнут применять к чужой базе (наблюдалось: run_migrations с
Db(path="/tmp/x.db") создавал таблицы в database.db текущего каталога).
"""
import pathlib
import re

SRC = pathlib.Path("migrations/env.py").read_text()
BODY = SRC.split("def _database_url", 1)[1].split("config.set_main_option", 1)[0]


def test_injected_url_checked_first():
    """Первая проверка в _database_url — уже установленный URL."""
    checks = re.findall(r'(injected|explicit|load_config)', BODY)
    assert checks[0] == "injected", f"первым идёт не injected: {checks}"


def test_env_fallback_still_there():
    assert "ALEMBIC_DB_URL" in BODY
    assert "load_config" in BODY


def test_loud_error_instead_of_default_file():
    """Молчаливый уход в database.db рядом хуже громкой ошибки."""
    assert "RuntimeError" in BODY


def test_runner_sets_url():
    src = pathlib.Path("infrastructure/database/migrations_runner.py").read_text()
    assert 'set_main_option("sqlalchemy.url"' in src
