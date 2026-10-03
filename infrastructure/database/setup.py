from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from config import Db


def create_engine(db: Db, echo: bool = False):
    return create_async_engine(db.sqlalchemy_url(), future=True, echo=echo)


def create_session_pool(engine):
    return async_sessionmaker(bind=engine, expire_on_commit=False)
