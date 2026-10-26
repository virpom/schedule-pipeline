"""План 048: на базе, поднятой миграциями, напоминания о звонках работают.

Baseline создавал в ``bell_reminder`` колонку ``key`` (VARCHAR(32)), а
модель и боевая база называют её ``event_key`` (VARCHAR(64)). Тесты
строят схему из моделей, поэтому дефект ловился только на развёртывании
по миграциям: ``is_sent``/``mark_sent`` падали с ``no such column``, и
звонки не приходили никогда.

Здесь схема поднимается alembic-ом, а не ``create_all``.
"""
import asyncio
import datetime as dt
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from infrastructure.database.models import BellReminder
from infrastructure.database.repo.requests import RequestsRepo

ROOT = Path(__file__).resolve().parents[1]


def _migrate_head(db_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ALEMBIC_DB_URL", f"sqlite+aiosqlite:///{db_path}")
    cfg = AlembicConfig(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    command.upgrade(cfg, "head")


def test_bell_reminder_works_on_migrated_db(tmp_path, monkeypatch):
    db_path = tmp_path / "migrated.db"
    _migrate_head(db_path, monkeypatch)

    engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        migrated = {c["name"]: str(c["type"]).upper()
                    for c in sa.inspect(engine).get_columns("bell_reminder")}
    finally:
        engine.dispose()
    model = {c.name: str(c.type).upper() for c in BellReminder.__table__.columns}
    assert migrated == model, "схема миграций разошлась с моделью BellReminder"

    async def scenario():
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
        pool = async_sessionmaker(engine, expire_on_commit=False)
        try:
            today = dt.date(2026, 10, 27)
            async with pool() as session:
                repo = RequestsRepo(session)
                assert await repo.reminders.is_sent(1, today, "s:1") is False
                await repo.reminders.mark_sent(1, today, "s:1")
                assert await repo.reminders.is_sent(1, today, "s:1") is True
                assert await repo.reminders.is_sent(1, today, "e:1") is False
                # Повтор не должен падать: уникальный ключ держит.
                await repo.reminders.mark_sent(1, today, "s:1")
                assert await repo.reminders.is_sent(1, today, "s:1") is True
        finally:
            await engine.dispose()

    asyncio.run(scenario())
