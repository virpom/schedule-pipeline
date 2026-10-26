import asyncio
import datetime
import logging
import time

from aiohttp import ClientSession

from common.schedule import bells_group, format_day, format_no_lessons
from config import Config
from infrastructure.database.repo.requests import RequestsRepo
from parsers import eios
from tgbot.services import alerts, photos, source_state, sync_eios, sync_vuz
from tgbot.services.broadcaster import broadcast_schedule
from tgbot.services.notify_edits import snapshot_past_days


async def _report_failure(bot, session_pool, config: Config, error: Exception) -> None:
    """Отличить «сайт лежит» от «сайт поменял структуру» и сказать админу.

    Разница принципиальная: лежащий сайт сам поднимется, и бот дождётся.
    Изменившаяся структура сама не починится — нужен человек, иначе бот
    будет молча работать на старых данных, пока не кончится окно из
    14 дней.
    """
    try:
        async with session_pool() as db:
            repo = RequestsRepo(db)
            if isinstance(error, eios.EiosParseError):
                await alerts.alert(
                    bot, repo, config, "structure",
                    f"Сайт отвечает, но файлы не разбираются:\n"
                    f"<code>{_short(error)}</code>\n\n"
                    f"Скорее всего изменилась структура страницы или файлов. "
                    f"Расписание работает на последних данных, но новые "
                    f"замены не подтягиваются.",
                )
            else:
                # Сеть, таймаут, 5xx — это «сайт лежит». Отдельного
                # уведомления не шлём: о недоступности пользователю и так
                # говорит предупреждение в расписании, а админ видит это
                # в /stats. Тревога нужна для того, что само не пройдёт.
                await alerts.clear(bot, repo, config, "structure",
                                   "Файлы снова разбираются.")
    except Exception:
        logging.exception("не удалось отправить тревогу")


def _short(error: Exception, limit: int = 300) -> str:
    text = str(error).strip() or type(error).__name__
    return text[:limit]


async def _report_partial_failure(bot, repo: RequestsRepo, config: Config,
                                  failed: list[str]) -> None:
    """Часть файлов не обновилась — сказать админу, а не только в лог.

    Раньше частичный сбой писал одну строку в лог и всё. 26.10.2026 файл
    замен отдавал 404 девять часов: админ не знал, студенты читали
    устаревшие замены. Лог читают, когда уже сломано.

    Отдельный ключ ``partial``, а не ``structure``: иначе две разные
    тревоги глушат друг друга по хешу текста.
    """
    names = ", ".join(failed)
    try:
        await alerts.alert(
            bot, repo, config, "partial",
            f"Не обновились файлы: <code>{names}</code>\n\n"
            f"Остальное расписание работает на последних данных. "
            f"Если так больше суток — проверь страницу расписания: "
            f"возможно, файл переименовали или убрали.",
        )
    except Exception:
        logging.exception("не удалось отправить тревогу о частичном сбое")


async def poll_once(bot, session_pool, config: Config) -> list[tuple[datetime.date, bool]]:
    """Синхронизировать расписание СПО из ЭИОС.

    Скачивает файлы колледжа, раскладывает их в слои ``base_lesson`` +
    ``substitution`` и материализует ближайшие дни в ``college_lesson``,
    откуда их читают все остальные части бота.

    Возвращает список изменившихся дней (для рассылки): ``(дата, новое_ли)``.
    """
    changes: list[tuple[datetime.date, bool]] = []
    vuz_changed = False
    async with ClientSession() as session:
        # Вуз обновляем отдельным шагом: у него свой источник и свой файл.
        # Сбой вуза не должен ломать колледж — и наоборот.
        try:
            async with session_pool() as db:
                repo = RequestsRepo(db)
                vuz_result = await sync_vuz.sync_once(session, repo)
                if vuz_result.get("failed"):
                    logging.warning("частичный сбой вуза: %s", vuz_result["failed"])
                else:
                    # Свой признак свежести: у вуза свой источник, и он
                    # может быть жив, когда сайт колледжа лежит.
                    await source_state.mark_ok_vuz(repo)
                # Файл вуза обновился — его замены тоже надо разослать.
                # Раньше здесь смотрели только на флаги колледжа, и
                # студент вуза не получал уведомлений вообще.
                vuz_changed = bool(vuz_result.get("full") or vuz_result.get("part"))
                for form in vuz_result.get("anchor_off") or []:
                    logging.error("якорь недель вуза не сходится (%s), "
                                  "проверь /setvuzanchor", form)
        except Exception:
            logging.exception("синхронизация вуза не удалась")

        try:
            async with session_pool() as db:
                repo = RequestsRepo(db)
                result = await sync_eios.sync_once(session, repo, config)
        except Exception as e:
            # Сайт недоступен целиком. Данные в слоях не тронуты — sync_once
            # бросает исключение до записи, — поэтому расписание продолжает
            # работать на последних известных данных. Просто не отмечаем
            # успех: is_stale() покажет, что свежесть под вопросом.
            logging.warning("ЭИОС недоступен: %s", e)
            result = None
            await _report_failure(bot, session_pool, config, e)

        # Успехом считаем только проход без единой ошибки. Если не доехали
        # замены — это именно то, о чём надо предупредить: постоянное
        # расписание верно, а изменений на день мы не знаем.
        if result is not None:
            failed = set(result.get("failed") or [])
            async with session_pool() as db:
                repo = RequestsRepo(db)
                if failed:
                    # Сайт отвечает, если доехал хоть один файл. Упали все
                    # запрошенные — это уже недоступность, свежесть не
                    # отмечаем: is_stale() честно скажет, что данные
                    # под вопросом.
                    if set(result.get("attempted") or []) - failed:
                        await source_state.mark_ok(repo)
                    await _report_partial_failure(bot, repo, config, sorted(failed))
                else:
                    await source_state.mark_ok(repo)
                    await alerts.clear(bot, repo, config, "partial",
                                       "Все файлы расписания снова обновляются.")

        # Материализуем ВСЕГДА, даже при сбое сайта и даже если файлы не
        # менялись: окно дат должно сдвигаться вперёд каждый день, иначе
        # через две недели расписание «кончится» — файлы те же, а новых
        # дат в college_lesson нет. Слои при сбое целы, так что
        # материализация соберёт те же данные на новые даты.
        async with session_pool() as db:
            repo = RequestsRepo(db)
            had_lessons = await repo.college_lessons.count_lessons()
            before = await repo.college_lessons.digest_by_date()
            try:
                await sync_eios.materialize(repo)
            except Exception:
                logging.exception("материализация не удалась")
            after = await repo.college_lessons.digest_by_date()

        # Рассылаем, только если источник реально изменился.
        college_changed = result is not None and (result["ochoe"] or result["zameny"])
        if not college_changed and not vuz_changed:
            return changes

        today = datetime.date.today()

        # Что именно поменялось. Флаг «файл изменился» слишком грубый: в
        # файле весь семестр, и одна исправленная строка тянула рассылку
        # на все даты замен сразу — человек получал полтора десятка
        # сообщений «расписание изменилось», хотя менялось одно.
        #
        # Материализация применяет и замены, и базовое расписание, поэтому
        # отпечаток даты ловит изменения из обоих источников. Отдельный
        # список дат замен больше не нужен: дата без замены тоже бывает
        # изменённой, и пересечение с get_dates() её бы выбросило.
        #
        # Группы тоже сравниваем: правка одной группы не должна будить
        # остальные 30. Иначе двадцать изменившихся дат дают 20×230
        # сообщений вместо 20 — по одному каждому, у кого ничего не
        # менялось.
        changed: dict[datetime.date, set[str]] = {}
        for date, groups in after.items():
            was = before.get(date, {})
            diff = {g for g, h in groups.items() if was.get(g) != h}
            if diff:
                changed[date] = diff

        # Изменилось, а отпечатка нет: правили день вне окна материализации
        # (оно 14 дней). Молчать нельзя — данные другие, — поэтому честно
        # показываем ближайшие дни всем: что именно поменялось, неизвестно.
        if ((result and result["ochoe"]) or vuz_changed) and not changed:
            for i in range(3):
                changed[today + datetime.timedelta(days=i)] = set()

        for date in sorted(changed):
            changes.append((date, had_lessons == 0 and date == today, changed[date]))
    return changes


async def notify_new_schedule(bot, session_pool, changes: list[tuple[datetime.date, bool, set[str]]], rate: float, photos_path: str) -> None:
    async with session_pool() as db:
        repo = RequestsRepo(db)
        bell, lunches = await repo.bell_schedule.get_context()
        subscribers = await repo.users.get_subscribed()
        chats = await repo.chats.get_all()
        group_course_map = await repo.users.get_group_course_map()

    items: list[tuple[int, str, str | None]] = []
    for date, is_new, groups in sorted(changes, key=lambda x: x[0]):
        weekday = photos.weekday_folder(date)
        prefix = "🆕 <b>Новое расписание</b>\n\n" if is_new else "🔄 <b>Расписание изменилось</b>\n\n"
        for user in subscribers:
            # Будить только тех, чья группа (или чьи пары) поменялась.
            # Пустой набор — «не знаем, что именно», тогда шлём всем.
            if groups:
                is_teacher = user.role == "teacher"
                if not is_teacher and user.group not in groups:
                    continue
                if is_teacher and not user.teacher_name:
                    continue
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
                cg = bells_group(user.group, user.course)
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
                    changes = await poll_once(bot, session_pool, config)
                    if changes:
                        await notify_new_schedule(bot, session_pool, changes, rate, config.photos_path)
                    last_poll = time.monotonic()
        except Exception:
            logging.exception("poll failed")
        await asyncio.sleep(10)
