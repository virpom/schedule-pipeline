import asyncio
import datetime
import hashlib
import logging

from aiohttp import ClientSession

from common.schedule import format_day
from config import Config
from infrastructure.database.repo.requests import RequestsRepo
from parsers import polar
from tgbot.services.broadcaster import send_message


async def poll_once(session_pool, config: Config) -> list[datetime.date]:
    new_dates: list[datetime.date] = []
    async with ClientSession() as session:
        html = await polar.fetch_html(session, config.schedule_url)
        links = polar.extract_daily_links(html, config.base_url)
        for date, url in links:
            try:
                async with session.get(url, raise_for_status=True) as resp:
                    data = await resp.read()
            except Exception as e:
                logging.warning("download failed %s: %s", url, e)
                continue

            digest = hashlib.md5(data).hexdigest()
            async with session_pool() as db:
                repo = RequestsRepo(db)
                prev = await repo.schedule_files.get_hash(date)
                if prev == digest:
                    continue

                lessons = polar.parse_docx(data, date)
                for lesson in lessons:
                    lesson["source_url"] = url
                await repo.college_lessons.replace_date(date, lessons)
                await repo.schedule_files.set_hash(date, digest)
                logging.info("parsed %s (%s) -> %d lessons", url, date, len(lessons))

                if prev is None:
                    new_dates.append(date)
    return new_dates


async def notify_new_schedule(bot, session_pool, dates: list[datetime.date]) -> None:
    async with session_pool() as db:
        repo = RequestsRepo(db)
        bell, lunches = await repo.bell_schedule.get_context()
        subscribers = await repo.users.get_subscribed()
    for date in sorted(dates):
        for user in subscribers:
            async with session_pool() as db:
                repo = RequestsRepo(db)
                lessons = await repo.college_lessons.get_for_group_date(user.group, date)
            text = format_day(date, lessons, bell, lunches, user.bell_detail)
            await send_message(bot, user.id, text)


async def poller_loop(bot, session_pool, config: Config) -> None:
    logging.info("poller started, interval=%ss", config.poll_interval)
    while True:
        try:
            new_dates = await poll_once(session_pool, config)
            if new_dates:
                await notify_new_schedule(bot, session_pool, new_dates)
        except Exception:
            logging.exception("poll failed")
        await asyncio.sleep(config.poll_interval)
