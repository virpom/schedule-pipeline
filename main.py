import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage

from config import load_config
from infrastructure.database import models  # noqa: F401  (register tables)
from infrastructure.database.models.base import Base
from infrastructure.database.repo.requests import RequestsRepo
from infrastructure.database.setup import create_engine, create_session_pool
from tgbot.handlers import routers_list
from tgbot.middlewares.database import DatabaseMiddleware
from tgbot.services.bell import bell_loop
from tgbot.services.poller import poller_loop


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(filename)s:%(lineno)d #%(levelname)-8s [%(asctime)s] - %(name)s - %(message)s",
    )


def register_global_middlewares(dp: Dispatcher, session_pool, config) -> None:
    dp.message.outer_middleware(DatabaseMiddleware(session_pool, config))
    dp.callback_query.outer_middleware(DatabaseMiddleware(session_pool, config))


async def on_startup(session_pool) -> None:
    async with session_pool() as session:
        repo = RequestsRepo(session)
        await repo.bell_schedule.seed_if_empty()


async def main() -> None:
    setup_logging()

    config = load_config(".env")
    engine = create_engine(config.db)
    session_pool = create_session_pool(engine)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    bot = Bot(token=config.tg_bot.token, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_routers(*routers_list)
    register_global_middlewares(dp, session_pool, config)

    await on_startup(session_pool)

    poller_task = asyncio.create_task(poller_loop(bot, session_pool, config))
    bell_task = asyncio.create_task(bell_loop(bot, session_pool, config))

    try:
        await dp.start_polling(bot)
    finally:
        poller_task.cancel()
        bell_task.cancel()
        await engine.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.error("Bot is stopped!")
