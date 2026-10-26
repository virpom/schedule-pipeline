from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from config import Db


def create_engine(db: Db, echo: bool = False):
    engine = create_async_engine(db.sqlalchemy_url(), future=True, echo=echo)

    # journal_mode=delete (по умолчанию) блокирует базу целиком на любую
    # запись: читатель ждёт писателя, писатель ждёт читателя. При 246
    # пользователях DatabaseMiddleware пишет в users на каждый тап, а
    # пересборка держит запись несколько секунд — второй староста ловил
    # «database is locked» через busy_timeout=5000.
    #
    # WAL разводит читателей и писателя. synchronous=NORMAL в WAL
    # безопасен (риск только при отключении питания, и теряется не
    # целостность, а последние транзакции) и заметно быстрее FULL на
    # десятках коммитов за пересборку.
    @event.listens_for(engine.sync_engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=10000")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()

    return engine


def create_session_pool(engine):
    return async_sessionmaker(bind=engine, expire_on_commit=False)
