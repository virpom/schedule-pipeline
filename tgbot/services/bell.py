import asyncio
import datetime
import logging

from common.schedule import course_group_from_group, day_type_from_date
from config import Config
from infrastructure.database.repo.requests import RequestsRepo
from tgbot.services.broadcaster import send_message


async def _tick(bot, session_pool, now: datetime.datetime) -> None:
    today = now.date()
    now_min = now.replace(second=0, microsecond=0).time()

    async with session_pool() as db:
        repo = RequestsRepo(db)
        bell, lunches = await repo.bell_schedule.get_context()
        subscribers = await repo.users.get_bell_subscribers()

    dt = day_type_from_date(today)
    for user in subscribers:
        async with session_pool() as db:
            repo = RequestsRepo(db)
            lessons = await repo.college_lessons.get_for_group_date(user.group, today)
        if not lessons:
            continue

        cg = course_group_from_group(user.group)
        lunch = lunches.get((dt, cg)) or lunches.get((dt, "I_IV"))

        events: list[tuple[datetime.time, str, str]] = []
        for l in lessons:
            para_end = getattr(l, "para_end", None) or l.para
            for p in range(l.para, para_end + 1):
                bs = bell.get((dt, cg, p)) or bell.get((dt, "I_IV", p))
                if not bs:
                    continue
                text = f"🔔 {p} пара · {l.subject}"
                if l.room:
                    text += f" · {l.room}"
                events.append((bs.start, f"p{p}", text))
        if lunch:
            events.append((lunch.lunch_start, "lunch", "🍽 Обед"))

        for t, key, text in events:
            if t != now_min:
                continue
            async with session_pool() as db:
                repo = RequestsRepo(db)
                if await repo.reminders.is_sent(user.id, today, key):
                    continue
                await repo.reminders.mark_sent(user.id, today, key)
            await send_message(bot, user.id, text)


async def bell_loop(bot, session_pool, config: Config) -> None:
    logging.info("bell loop started")
    while True:
        try:
            await _tick(bot, session_pool, datetime.datetime.now())
        except Exception:
            logging.exception("bell tick failed")
        await asyncio.sleep(30)
