from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from config import DbConfig


def create_engine(db: DbConfig, echo=False):
    return create_async_engine(
        db.construct_sqlalchemy_url(),
        query_cache_size=1200,
        # pool_size=20,
        # max_overflow=200,
        future=True,
        echo=echo,
    )


def create_session_pool(engine):
    return async_sessionmaker(bind=engine, expire_on_commit=False)
