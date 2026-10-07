import asyncio
import datetime
import hashlib
import logging
import time

from aiohttp import ClientSession

from common.schedule import format_day, format_no_lessons
from config import Config
from infrastructure.database.repo.requests import RequestsRepo
from parsers import polar
from tgbot.services import photos
from tgbot.services.broadcaster import broadcast_schedule


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

                lessons, no_lessons = polar.parse_docx(data, date)
                for lesson in lessons:
                    lesson["source_url"] = url
                await repo.college_lessons.replace_date(date, lessons)
                await repo.no_lessons.replace_date(date, no_lessons)
                await repo.schedule_files.set_hash(date, digest)
                logging.info("parsed %s (%s) -> %d lessons, %d no-lessons", url, date, len(lessons), len(no_lessons))

                if prev is None:
                    new_dates.append(date)
    return new_dates


async def notify_new_schedule(bot, session_pool, dates: list[datetime.date], rate: float, photos_path: str) -> None:
    async with session_pool() as db:
        repo = RequestsRepo(db)
        bell, lunches = await repo.bell_schedule.get_context()
        subscribers = await repo.users.get_subscribed()
        chats = await repo.chats.get_all()

    items: list[tuple[int, str, str | None]] = []
    for date in sorted(dates):
        weekday = photos.weekday_folder(date)
        for user in subscribers:
            async with session_pool() as db:
                repo = RequestsRepo(db)
                if user.role == "teacher" and user.teacher_name:
                    lessons = await repo.college_lessons.get_for_teacher_date(user.teacher_name, date)
                    note = None
                else:
                    lessons = await repo.college_lessons.get_for_group_date(user.group, date)
                    note = await repo.no_lessons.get_note(date, user.group) if not lessons else None
            is_teacher = user.role == "teacher"
            if lessons:
                text = format_day(
                    date, lessons, bell, lunches, user.bell_detail,
                    meta="group" if is_teacher else "teacher",
                    show_rov=not is_teacher,
                )
            else:
                text = format_no_lessons(date, note)
            photo = photos.random_photo(photos_path, weekday) if (user.send_image and not is_teacher) else None
            items.append((user.id, text, photo))
        for chat in chats:
            if not chat.group:
                continue
            async with session_pool() as db:
                repo = RequestsRepo(db)
                lessons = await repo.college_lessons.get_for_group_date(chat.group, date)
                note = await repo.no_lessons.get_note(date, chat.group) if not lessons else None
            if lessons:
                text = format_day(date, lessons, bell, lunches, "brief")
            else:
                text = format_no_lessons(date, note)
            photo = photos.random_photo(photos_path, weekday)
            items.append((chat.id, text, photo))

    await broadcast_schedule(bot, items, rate=rate)


def _in_night(now: datetime.datetime, start_str: str, end_str: str) -> bool:
    if not start_str or not end_str:
        return False
    try:
        start = datetime.time.fromisoformat(start_str)
        end = datetime.time.fromisoformat(end_str)
    except ValueError:
        return False
    if start == end:
        return False
    t = now.time()
    if start < end:
        return start <= t < end
    return t >= start or t < end


async def poller_loop(bot, session_pool, config: Config) -> None:
    logging.info("poller started")
    last_poll = 0.0
    while True:
        try:
            async with session_pool() as db:
                repo = RequestsRepo(db)
                settings = await repo.settings.get_all()

            interval = int(settings["poll_interval"])
            rate = float(settings["notify_rate"])
            now = datetime.datetime.now()

            if not _in_night(now, settings["night_start"], settings["night_end"]):
                if time.monotonic() - last_poll >= interval:
                    new_dates = await poll_once(session_pool, config)
                    if new_dates:
                        await notify_new_schedule(bot, session_pool, new_dates, rate, config.photos_path)
                    last_poll = time.monotonic()
        except Exception:
            logging.exception("poll failed")
        await asyncio.sleep(10)
