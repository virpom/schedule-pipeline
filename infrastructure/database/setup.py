from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from config import DbConfig


def create_engine(db: DbConfig, echo=False):
    return create_async_engine(
        db.construct_sqlalchemy_url(),
        pool_size=20,
        max_overflow=200,
        pool_pre_ping=True,
        pool_recycle=3600,
        future=True,
        echo=echo,
    )


def create_session_pool(engine):
    return async_sessionmaker(
        bind=engine,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False
    )
