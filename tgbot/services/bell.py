import asyncio
import datetime
import logging

from common.schedule import (
    BELL_FULL,
    BELL_START_END,
    course_group_from_course,
    course_group_from_group,
    day_type_from_date,
)
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
        group_course_map = await repo.users.get_group_course_map()

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

        is_teacher = user.role == "teacher"
        own_cg = None if is_teacher else course_group_from_course(user.course)

        def _cg(group: str) -> str:
            if own_cg:
                return own_cg
            if is_teacher:
                return group_course_map.get(group) or course_group_from_group(group)
            return course_group_from_group(group)

        events: list[tuple[datetime.time, str, str]] = []
        for l in lessons:
            cg = _cg(l.group)
            para_end = getattr(l, "para_end", None) or l.para
            lunch = lunches.get((dt, cg)) or lunches.get((dt, "I_IV"))

            # start bell
            bs0 = bell.get((dt, cg, l.para)) or bell.get((dt, "I_IV", l.para))
            if bs0 and user.bell_mode in (BELL_START_END, BELL_FULL):
                text = f"🔔 {l.para} пара · {l.subject}"
                if l.room:
                    text += f" · {l.room}"
                events.append((bs0.start, f"s:{l.para}", text))

            for p in range(l.para, para_end + 1):
                bp = bell.get((dt, cg, p)) or bell.get((dt, "I_IV", p))
                if not bp:
                    continue
                # break between academic hours (skip when it coincides with lunch inside)
                if user.bell_mode == BELL_FULL and bp.h1_end != bp.h2_start:
                    if not (lunch and lunch.position == "inside" and lunch.para == p):
                        events.append((bp.h1_end, f"h1:{p}", "🔔 Перемена"))
                        events.append((bp.h2_start, f"h2:{p}", "🔔 Перемена закончилась"))
                # end of lesson (skip when lunch follows this para at the same minute)
                if p == para_end and user.bell_mode in (BELL_START_END, BELL_FULL):
                    if not (lunch and lunch.position == "after" and lunch.para == p):
                        events.append((bp.end, f"e:{p}", "🔔 Конец пары"))

        # lunch (big break) — anchored to the para where lunch sits (2-я пара)
        if user.bell_mode == BELL_FULL:
            lunch_lesson = next(
                (l for l in lessons if l.para <= 2 <= (getattr(l, "para_end", None) or l.para)),
                None,
            )
            if lunch_lesson:
                lunch = lunches.get((dt, _cg(lunch_lesson.group))) or lunches.get((dt, "I_IV"))
                if lunch:
                    events.append((lunch.lunch_start, "lunch", "🍽 Обед"))
                    events.append((lunch.lunch_end, "lunch_end", "🍽 Обед закончился"))

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
