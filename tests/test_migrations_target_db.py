"""Миграции идут в ту базу, которую указали, а не в database.db рядом.

План 052. `migrations_runner` ставил URL через `set_main_option`, но
`migrations/env.py` при импорте затирал его безусловно и брал URL из
окружения. Если `SQLITE_PATH` не задан, миграции молча уходили в
`database.db` в текущем каталоге, а приложение открывало другую базу и
не находило таблиц.

Наблюдалось живьём: `run_migrations_sync` с `Db(path="/tmp/x.db")`
создавал 16 таблиц в `./database.db`, а `/tmp/x.db` оставался пустым.
На проде не проявлялось только потому, что `SQLITE_PATH` в окружении
случайно совпадал с тем, что ставил runner.
"""
import os
import sqlite3
import tempfile
from pathlib import Path

from config import Config, Db, TgBot
from infrastructure.database.migrations_runner import run_migrations_sync


def _cfg(path: str) -> Config:
    return Config(tg_bot=TgBot(token="x", admin_ids=[]), db=Db(path=path),
                  schedule_url="x", photos_path=".")


def test_migrations_go_to_given_path():
    """Главное: таблицы появились именно в указанном файле."""
    with tempfile.TemporaryDirectory() as tmp:
        target = str(Path(tmp) / "target.db")
        run_migrations_sync(_cfg(target))

        assert Path(target).exists(), "файл базы не создан"
        conn = sqlite3.connect(target)
        try:
            tables = [r[0] for r in conn.execute(
                "select name from sqlite_master where type='table'")]
            assert len(tables) >= 16, f"таблиц всего {len(tables)}"
            version = conn.execute("select version_num from alembic_version").fetchone()
            assert version[0] == "0007_bell_reminder"
        finally:
            conn.close()


def test_no_stray_database_in_cwd():
    """Никакого database.db рядом с текущим каталогом.

    Именно это и случалось: миграции уходили в файл по умолчанию.
    """
    cwd_before = set(os.listdir("."))
    with tempfile.TemporaryDirectory() as tmp:
        run_migrations_sync(_cfg(str(Path(tmp) / "x.db")))
        assert "database.db" not in set(os.listdir(".")) - cwd_before


def test_schema_matches_models():
    """Миграции воспроизводят схему, а не что попало.

    `college_lesson.id` и уникальный ключ появились только в 0007 —
    если миграции ушли не туда, здесь окажется 11 колонок без id.
    """
    with tempfile.TemporaryDirectory() as tmp:
        target = str(Path(tmp) / "schema.db")
        run_migrations_sync(_cfg(target))

        conn = sqlite3.connect(target)
        try:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(college_lesson)")]
            assert "id" in cols, "нет id — миграция 0007 не применилась"
            assert len(cols) == 12, cols

            idx = list(conn.execute("PRAGMA index_list(college_lesson)"))
            # SQLite сам называет автоиндекс, поэтому проверяем флаг
            # уникальности (5-я колонка), а не имя.
            assert any(r[2] == 1 for r in idx), f"нет уникального ключа: {idx}"
            cols_in = [r[2] for r in conn.execute("PRAGMA index_info(sqlite_autoindex_college_lesson_1)")]
            assert cols_in == ["date", "group", "para"], cols_in
        finally:
            conn.close()


def test_bell_reminder_has_event_key():
    """`event_key`, а не `key`: иначе напоминания о звонках не работают."""
    with tempfile.TemporaryDirectory() as tmp:
        target = str(Path(tmp) / "bell.db")
        run_migrations_sync(_cfg(target))

        conn = sqlite3.connect(target)
        try:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(bell_reminder)")]
            assert "event_key" in cols, cols
            assert "key" not in cols, cols
        finally:
            conn.close()
