"""Применение миграций alembic при старте приложения.

Запускается на отдельном (временном) движке и закрывает его сразу —
иначе alembic, выполняемый внутри основного пула соединений, оставляет
соединение занятым и блокирует последующие запросы приложения.

Особый случай: база, созданная до внедрения alembic (через
Base.metadata.create_all), не имеет таблицы alembic_version. Её нельзя
просто прогнать через upgrade — 0001_baseline попытается создать уже
существующие таблицы. Поэтому такую базу сначала «помечаем» как baseline,
проставив версию напрямую.
"""
import logging
from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import create_engine, inspect, text

from config import Config

BASELINE_REVISION = "0001_baseline"

# Таблицы, по наличию которых определяем «старую» (до alembic) базу.
_LEGACY_MARKERS = ("users", "college_lesson")


def _sync_url(config: Config) -> str:
    """Синхронный URL: alembic проще запускать без asyncio."""
    return "sqlite:///" + config.db.path


def _alembic_config(config: Config) -> AlembicConfig:
    root = Path(__file__).resolve().parents[2]
    cfg = AlembicConfig(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "migrations"))
    cfg.set_main_option("sqlalchemy.url", _sync_url(config))
    return cfg


def _current_revision(conn) -> str | None:
    if not inspect(conn).has_table("alembic_version"):
        return None
    row = conn.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).first()
    return row[0] if row else None


def _looks_like_legacy_db(conn) -> bool:
    inspector = inspect(conn)
    return all(inspector.has_table(t) for t in _LEGACY_MARKERS)


def _has_version_table(conn) -> bool:
    return inspect(conn).has_table("alembic_version")


def _stamp_baseline(conn) -> None:
    """Проставить baseline-версию напрямую, не запуская env.py."""
    conn.execute(text("CREATE TABLE IF NOT EXISTS alembic_version "
                      "(version_num VARCHAR(32) NOT NULL)"))
    conn.execute(text("DELETE FROM alembic_version"))
    conn.execute(text("INSERT INTO alembic_version (version_num) VALUES (:v)"),
                 {"v": BASELINE_REVISION})
    conn.commit()


def run_migrations_sync(config: Config) -> None:
    """Синхронный запуск миграций на отдельном движке."""
    engine = create_engine(_sync_url(config), future=True)
    try:
        with engine.connect() as conn:
            current = _current_revision(conn)
            if current is None and _has_version_table(conn):
                # Таблица версий есть, но пуста: схема уже под alembic, и
                # `alembic stamp head` тут угадывает — down_revision
                # неизвестен. Угадывание в любую сторону портит базу:
                # «baseline» прогоняет все миграции заново на живой схеме
                # (OperationalError: table base_lesson already exists),
                # «head» объявляет недоприменённую базу актуальной.
                # Пере-применение частично завершает upgrade и оставляет
                # версию на середине — это и воспроизводит пустую таблицу.
                raise RuntimeError(
                    "Таблица alembic_version пуста, а схема на месте: "
                    "неизвестно, какие миграции применены. Проверь схему и "
                    "проставь версию вручную (alembic stamp <revision>); "
                    "восстанавливай из дампа через "
                    "'sqlite3 old.db .dump | sqlite3 new.db', а не через "
                    "create_all"
                )
            if current is None and _looks_like_legacy_db(conn):
                logging.info("alembic: существующая БД — помечаю как %s", BASELINE_REVISION)
                _stamp_baseline(conn)
            elif current is None:
                logging.info("alembic: пустая БД — применяю все миграции")

        # Соединение передаём явно: env.py не поднимает свой event loop
        # и не строит второй движок по URL. Раньше URL из runner-а
        # затирался внутри env.py, и миграции уходили в database.db
        # рядом с текущим каталогом (план 052).
        cfg = _alembic_config(config)
        with engine.begin() as conn:
            cfg.attributes["connection"] = conn
            command.upgrade(cfg, "head")
    finally:
        engine.dispose()

    logging.info("alembic: миграции применены")


async def run_migrations(engine, config: Config) -> None:
    """Async-обёртка для вызова из main(): уводит работу в поток."""
    import asyncio
    await asyncio.to_thread(run_migrations_sync, config)
