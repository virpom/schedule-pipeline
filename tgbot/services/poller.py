import asyncio
import datetime
import hashlib
import logging
import time

from aiohttp import ClientSession

from common.schedule import course_group_from_course, format_day, format_no_lessons
from config import Config
from infrastructure.database.repo.requests import RequestsRepo
from tgbot.services import photos, sync_eios
from tgbot.services.broadcaster import broadcast_schedule
from tgbot.services.notify_edits import snapshot_past_days


_failed: dict[str, float] = {}


async def poll_once(session_pool, config: Config, failed_cooldown: int = 1800) -> list[tuple[datetime.date, bool]]:
    """Синхронизировать расписание СПО из ЭИОС.

    Скачивает файлы колледжа, раскладывает их в слои ``base_lesson`` +
    ``substitution`` и материализует ближайшие дни в ``college_lesson``,
    откуда их читают все остальные части бота.

    Возвращает список изменившихся дней (для рассылки): ``(дата, новое_ли)``.
    """
    changes: list[tuple[datetime.date, bool]] = []
    async with ClientSession() as session:
        try:
            async with session_pool() as db:
                repo = RequestsRepo(db)
                result = await sync_eios.sync_once(session, repo, config)
        except Exception as e:
            async with session_pool() as db:
                await RequestsRepo(db).settings.set("site_down", "1")
            logging.warning("ЭИОС недоступен: %s", e)
            return changes

        async with session_pool() as db:
            await RequestsRepo(db).settings.set("site_down", "0")

        # Материализуем ВСЕГДА, даже если файлы не менялись: окно дат должно
        # сдвигаться вперёд каждый день, иначе через две недели расписание
        # «кончится» — файлы те же, а новых дат в college_lesson нет.
        async with session_pool() as db:
            repo = RequestsRepo(db)
            had_lessons = await repo.college_lessons.count_lessons()
            await sync_eios.materialize(repo)

        # Рассылаем, только если источник реально изменился.
        if not (result["ochoe"] or result["zameny"]):
            return changes

        today = datetime.date.today()

        # Замены приходят на конкретные даты (листок выдаётся сразу на
        # несколько дней, например СБ + ПН). Фиксированное окно «сегодня + 2»
        # их теряло: замена на понедельник, пришедшая в пятницу, не попадала.
        async with session_pool() as db:
            repo = RequestsRepo(db)
            dates = set(await repo.substitutions.get_dates(today))

        if result["ochoe"]:
            # Сменилось базовое расписание — показываем ближайшие дни.
            dates |= {today + datetime.timedelta(days=i) for i in range(3)}

        for date in sorted(dates):
            changes.append((date, had_lessons == 0 and date == today))
    return changes


async def notify_new_schedule(bot, session_pool, changes: list[tuple[datetime.date, bool]], rate: float, photos_path: str) -> None:
    async with session_pool() as db:
        repo = RequestsRepo(db)
        bell, lunches = await repo.bell_schedule.get_context()
        subscribers = await repo.users.get_subscribed()
        chats = await repo.chats.get_all()
        group_course_map = await repo.users.get_group_course_map()

    items: list[tuple[int, str, str | None]] = []
    for date, is_new in sorted(changes, key=lambda x: x[0]):
        weekday = photos.weekday_folder(date)
        prefix = "🆕 <b>Новое расписание</b>\n\n" if is_new else "🔄 <b>Расписание изменилось</b>\n\n"
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
            if is_teacher:
                gcg = group_course_map or None
            else:
                cg = course_group_from_course(user.course)
                gcg = {user.group: cg} if cg else None
            if lessons:
                text = format_day(
                    date, lessons, bell, lunches, user.bell_detail,
                    meta="group" if is_teacher else "teacher",
                    show_rov=not is_teacher,
                    group_course_group=gcg,
                )
            else:
                text = format_no_lessons(date, note)
            photo = photos.random_photo(photos_path, weekday) if (user.send_image and not is_teacher) else None
            items.append((user.id, prefix + text, photo))
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
            items.append((chat.id, prefix + text, photo))

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
    last_snapshot = 0.0
    while True:
        try:
            async with session_pool() as db:
                repo = RequestsRepo(db)
                settings = await repo.settings.get_all()

            interval = int(settings["poll_interval"])
            rate = float(settings["notify_rate"])
            failed_cooldown = int(settings.get("failed_cooldown", 1800) or 1800)
            now = datetime.datetime.now()

            # Архив прошедших дней: раз в час, чтобы зафиксировать, что было
            # (сайт может обновить файл задним числом — история не потеряется).
            if time.monotonic() - last_snapshot >= 3600:
                try:
                    async with session_pool() as db:
                        await snapshot_past_days(RequestsRepo(db))
                except Exception:
                    logging.exception("snapshot failed")
                last_snapshot = time.monotonic()

            if not _in_night(now, settings["night_start"], settings["night_end"]):
                if time.monotonic() - last_poll >= interval:
                    changes = await poll_once(session_pool, config, failed_cooldown)
                    if changes:
                        await notify_new_schedule(bot, session_pool, changes, rate, config.photos_path)
                    last_poll = time.monotonic()
        except Exception:
            logging.exception("poll failed")
        await asyncio.sleep(10)
