import asyncio
import logging
import os
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

from config import load_config
from infrastructure.database import models  # noqa: F401  (register tables)
from infrastructure.database.models.base import Base

config = context.config

# Не перетирать логирование приложения. fileConfig из alembic.ini ставит
# root.level = WARNING, и после run_migrations все logging.info в проекте
# уходят в пустоту — включая «poller started» и итоги рассылок. В консоли
# alembic.ini нужен для ручных вызовов; когда логирование уже настроено
# (main.py:setup_logging), трогать его нельзя.
if config.config_file_name is not None and not logging.getLogger().handlers:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    """Resolve DB URL: ALEMBIC_DB_URL wins, else SQLITE_PATH from .env."""
    explicit = os.getenv("ALEMBIC_DB_URL")
    if explicit:
        return explicit
    env_path = os.getenv("ENV_FILE", ".env")
    try:
        return load_config(env_path).db.sqlalchemy_url()
    except Exception:
        return "sqlite+aiosqlite:///database.db"


config.set_main_option("sqlalchemy.url", _database_url())


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    # Если соединение передано извне (запуск из приложения), используем его —
    # свой event loop поднимать нельзя, мы уже внутри работающего.
    injected = config.attributes.get("connection")
    if injected is not None:
        do_run_migrations(injected)
        return
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
