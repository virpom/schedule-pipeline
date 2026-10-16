"""Применение миграций alembic при старте приложения.

Особый случай: база, созданная до внедрения alembic (через
Base.metadata.create_all), не имеет таблицы alembic_version. Её нельзя
просто прогнать через upgrade — 0001_baseline попытается создать уже
существующие таблицы. Поэтому такую базу сначала «помечаем» как baseline,
проставив версию напрямую (без прогона env.py alembic).
"""
import logging
from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import inspect, text

from config import Config

BASELINE_REVISION = "0001_baseline"

# Таблицы, по наличию которых определяем «старую» (до alembic) базу.
_LEGACY_MARKERS = ("users", "college_lesson")


def _alembic_config(config: Config) -> AlembicConfig:
    root = Path(__file__).resolve().parents[2]
    cfg = AlembicConfig(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "migrations"))
    cfg.set_main_option("sqlalchemy.url", config.db.sqlalchemy_url())
    return cfg


def _current_revision(sync_conn) -> str | None:
    """Текущая версия из alembic_version (None, если таблицы нет или пусто)."""
    if not inspect(sync_conn).has_table("alembic_version"):
        return None
    row = sync_conn.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).first()
    return row[0] if row else None


def _looks_like_legacy_db(sync_conn) -> bool:
    inspector = inspect(sync_conn)
    return all(inspector.has_table(t) for t in _LEGACY_MARKERS)


def _stamp_baseline(sync_conn) -> None:
    """Проставить baseline-версию напрямую, не запуская env.py."""
    sync_conn.execute(text("CREATE TABLE IF NOT EXISTS alembic_version "
                           "(version_num VARCHAR(32) NOT NULL)"))
    sync_conn.execute(text("DELETE FROM alembic_version"))
    sync_conn.execute(text("INSERT INTO alembic_version (version_num) VALUES (:v)"),
                      {"v": BASELINE_REVISION})


def upgrade_sync(sync_conn, config: Config) -> None:
    """Вызывается внутри engine.begin() (run_sync)."""
    current = _current_revision(sync_conn)

    if current is None and _looks_like_legacy_db(sync_conn):
        logging.info("alembic: существующая БД — помечаю как %s", BASELINE_REVISION)
        _stamp_baseline(sync_conn)
    elif current is None:
        logging.info("alembic: пустая БД — применяю все миграции")

    cfg = _alembic_config(config)
    cfg.attributes["connection"] = sync_conn
    command.upgrade(cfg, "head")


async def run_migrations(engine, config: Config) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(lambda sc: upgrade_sync(sc, config))
    logging.info("alembic: миграции применены")
