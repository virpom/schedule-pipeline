import asyncio
import datetime
import logging

from common.schedule import (
    BELL_ALL,
    BELL_PARA,
    BELL_PARA_BREAK,
    BELL_PARA_LUNCH,
    course_group_from_group,
    day_type_from_date,
)
from config import Config
from infrastructure.database.repo.requests import RequestsRepo
from tgbot.services.broadcaster import send_message


def _user_has_mode(mode: str) -> bool:
    return mode in (BELL_PARA, BELL_PARA_BREAK, BELL_PARA_LUNCH, BELL_ALL)


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
            if user.role == "teacher" and user.teacher_name:
                lessons = await repo.college_lessons.get_for_teacher_date(user.teacher_name, today)
            else:
                lessons = await repo.college_lessons.get_for_group_date(user.group, today)
        if not lessons:
            continue

        events: list[tuple[datetime.time, str, str]] = []
        for l in lessons:
            cg = course_group_from_group(l.group)
            para_end = getattr(l, "para_end", None) or l.para
            lunch = lunches.get((dt, cg)) or lunches.get((dt, "I_IV"))

            # start bell
            bs = bell.get((dt, cg, l.para)) or bell.get((dt, "I_IV", l.para))
            if bs and user.bell_mode in (BELL_PARA, BELL_PARA_BREAK, BELL_PARA_LUNCH, BELL_ALL):
                text = f"🔔 {l.para} пара · {l.subject}"
                if l.room:
                    text += f" · {l.room}"
                events.append((bs.start, f"s:{l.para}", text))

            # break (end of lesson)
            be = bell.get((dt, cg, para_end)) or bell.get((dt, "I_IV", para_end))
            if be and user.bell_mode in (BELL_PARA_BREAK, BELL_ALL):
                events.append((be.end, f"b:{para_end}", "🔔 Перемена"))

            # lunch
            if lunch and user.bell_mode in (BELL_PARA_LUNCH, BELL_ALL):
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
