"""План 166. Пустая `alembic_version` на живой базе не должна её откатывать.

`_current_revision` возвращал `None` в двух разных случаях: таблицы
версий нет (база до alembic) и таблица есть, но пуста (база под
alembic с потерянной строкой версии). Второй случай уходил в
`_stamp_baseline`, версия становилась `0001_baseline`, и
`command.upgrade(cfg, "head")` заново прогонял 0002_editors на живой
схеме:

    OperationalError: table base_lesson already exists

Контейнер падал на старте, `restart=unless-stopped` поднимал его снова,
и цикл не кончался, пока кто-то руками не проставит версию.

Наблюдалось: fully migrated база (0011_drop_bell_notify), затем
`DELETE FROM alembic_version` — `run_migrations_sync` падал с ошибкой
SQLite про base_lesson вместо внятной причины.
"""
import sqlite3
import tempfile
from pathlib import Path

import pytest

from config import Config, Db, TgBot
from infrastructure.database.migrations_runner import run_migrations_sync


def _cfg(path: str) -> Config:
    return Config(tg_bot=TgBot(token="x", admin_ids=[]), db=Db(path=path),
                  schedule_url="x", photos_path=".")


def _version(path: str) -> list:
    conn = sqlite3.connect(path)
    try:
        return conn.execute("select version_num from alembic_version").fetchall()
    finally:
        conn.close()


def _make_migrated_db(tmp: str) -> str:
    target = str(Path(tmp) / "live.db")
    run_migrations_sync(_cfg(target))
    conn = sqlite3.connect(target)
    try:
        conn.execute("DELETE FROM alembic_version")
        conn.commit()
    finally:
        conn.close()
    assert _version(target) == [], "версия не затёрта — тест не воспроизводит случай"
    return target


def test_empty_version_table_does_not_rerun_migrations():
    """Главное: причина в ошибке, а не `table base_lesson already exists`."""
    with tempfile.TemporaryDirectory() as tmp:
        target = _make_migrated_db(tmp)

        with pytest.raises(RuntimeError) as exc:
            run_migrations_sync(_cfg(target))

        msg = str(exc.value)
        assert "alembic_version" in msg, msg
        assert "stamp" in msg, msg
        # База не тронута: ничего не переприменено и не удалено.
        assert _version(target) == [], _version(target)
        conn = sqlite3.connect(target)
        try:
            tables = {r[0] for r in conn.execute(
                "select name from sqlite_master where type='table'")}
        finally:
            conn.close()
        assert "base_lesson" in tables and "users" in tables, tables


def test_fresh_db_still_migrates():
    """Пустая база (таблицы версий нет вообще) по-прежнему накатывается.

    Гард не должен ловить настоящий первый запуск.
    """
    with tempfile.TemporaryDirectory() as tmp:
        target = str(Path(tmp) / "fresh.db")
        run_migrations_sync(_cfg(target))

        conn = sqlite3.connect(target)
        try:
            tables = {r[0] for r in conn.execute(
                "select name from sqlite_master where type='table'")}
        finally:
            conn.close()
        assert len(tables) >= 16, tables
        assert len(_version(target)) == 1, _version(target)
