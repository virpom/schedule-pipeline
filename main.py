import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage, DefaultKeyBuilder

from config import Config, load_config
from infrastructure.database.repo.requests import RequestsRepo
from infrastructure.database.setup import create_engine, create_session_pool
from parsers.data_processor import ScheduleParser
from parsers.pdf_parser import PDFScheduleExtractor
from tgbot.handlers import routers_list
from tgbot.middlewares.database import DatabaseMiddleware
from tgbot.services import broadcaster


async def on_startup(bot: Bot, admin_ids: list[int]):
    await broadcaster.broadcast(bot, admin_ids, "Бот запущен")


def register_global_middlewares(dp: Dispatcher, session_pool=None):
    middleware_types = [
        DatabaseMiddleware(session_pool=session_pool)
    ]

    for middleware_type in middleware_types:
        dp.message.outer_middleware(middleware_type)
        dp.callback_query.outer_middleware(middleware_type)


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(filename)s:%(lineno)d #%(levelname)-8s [%(asctime)s] - %(name)s - %(message)s",
    )
    logger = logging.getLogger(__name__)
    logger.info("Starting bot")


def get_storage(config: Config):
    if config.tg_bot.use_redis:
        return RedisStorage.from_url(
            config.redis.dsn(),
            key_builder=DefaultKeyBuilder(with_bot_id=True, with_destiny=True),
        )
    else:
        return MemoryStorage()


async def load_classes_data(repo: RequestsRepo, path: str):
    info, df = PDFScheduleExtractor(path).extract_schedule()
    stream_lessons = ScheduleParser(info, df).parse_schedule()
    stream_id = await repo.lessons.get_or_create_stream_id(stream_lessons.stream)
    await repo.lessons.bulk_add_lessons(stream_lessons.lessons, stream_id)

    group_codes = {lesson.group_code for lesson in stream_lessons.lessons}
    for group_code in group_codes:
        await repo.student_group.get_or_create_group(group_code, stream_id)


async def main():
    setup_logging()

    config = load_config(".env")
    storage = get_storage(config)

    bot = Bot(token=config.tg_bot.token, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher(storage=storage)

    dp.include_routers(*routers_list)

    engine = create_engine(config.db)
    session_pool = create_session_pool(engine)

    register_global_middlewares(dp, session_pool)

    async with session_pool() as session:
        repo = RequestsRepo(session)
        await repo.lessons.delete_all()
        count = 0
        for filename in os.scandir("schedule_data"):
            try:
                logging.info(f"Parsing '{filename.path}'")
                await load_classes_data(repo, filename.path)
            except (AttributeError, ValueError) as e:
                logging.error(f"{filename.path:50}: {e}")
            else:
                count += 1
        logging.info(f"{count} files successful parsed")
    await on_startup(bot, config.tg_bot.admin_ids)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.error("Bot is stopped!")
