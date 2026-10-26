"""WAL включён, иначе запись блокирует базу целиком.

План 010. `journal_mode=delete` (по умолчанию) означает: любая запись
блокирует базу целиком — читатель ждёт писателя, писатель ждёт читателя.

На проде это било трижды: DatabaseMiddleware пишет в `users` на каждый
тап (246 пользователей — постоянный поток коротких записей), пересборка
держит запись несколько секунд, а `busy_timeout=5000` через пять секунд
ожидания даёт `database is locked` прямо в обработчике.
"""
import tempfile
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from config import Db
from infrastructure.database.setup import create_engine


async def _pragmas(path: str) -> dict:
    engine = create_engine(Db(path=path))
    try:
        async with engine.connect() as conn:
            out = {}
            for name in ("journal_mode", "busy_timeout", "synchronous"):
                out[name] = (await conn.execute(text(f"PRAGMA {name}"))).scalar()
            return out
    finally:
        await engine.dispose()


async def test_wal_enabled():
    """Главное: journal_mode = wal, а не delete."""
    with tempfile.TemporaryDirectory() as tmp:
        p = str(Path(tmp) / "t.db")
        pragmas = await _pragmas(p)
        assert pragmas["journal_mode"] == "wal", "WAL не включён — план 010"


async def test_busy_timeout_raised():
    """Пять секунд мало: пересборка держит запись дольше."""
    with tempfile.TemporaryDirectory() as tmp:
        p = str(Path(tmp) / "t.db")
        assert (await _pragmas(p))["busy_timeout"] >= 10000


async def test_synchronous_normal():
    """NORMAL (1) безопасен в WAL и быстрее FULL (2)."""
    with tempfile.TemporaryDirectory() as tmp:
        p = str(Path(tmp) / "t.db")
        assert (await _pragmas(p))["synchronous"] == 1


async def test_reader_does_not_block_writer():
    """Смысл WAL: открытая читающая транзакция не мешает писать.

    В режиме delete этот тест зависает до busy_timeout и падает.
    """
    from infrastructure.database.models import Base, Setting

    with tempfile.TemporaryDirectory() as tmp:
        p = str(Path(tmp) / "t.db")
        engine = create_engine(Db(path=p))
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            pool = async_sessionmaker(engine, expire_on_commit=False)

            async with pool() as reader:
                # Держим открытое чтение.
                await reader.execute(text("select count(*) from setting"))

                async with pool() as writer:
                    writer.add(Setting(key="probe", value="1"))
                    await writer.commit()

                rows = list(await reader.execute(text("select count(*) from setting")))
                assert rows[0][0] == 1
        finally:
            await engine.dispose()
