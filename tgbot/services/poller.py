import asyncio
import datetime
import logging
import time

from aiohttp import ClientSession

from common.schedule import bells_group, format_day, format_no_lessons
from config import Config
from infrastructure.database.repo.requests import RequestsRepo
from parsers import eios, vuz
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
            if isinstance(error, (eios.EiosParseError, vuz.VuzParseError)):
                # Вуз бросает свой VuzParseError. Раньше он уходил в
                # общий except у синхронизации вуза, и админ не узнавал,
                # что структура файла вуза сломалась: бот молча работал
                # на старых данных, пока не кончится окно 14 дней.
                where = "вуза" if isinstance(error, vuz.VuzParseError) else ""
                await alerts.alert(
                    bot, repo, config, "structure",
                    f"Сайт отвечает, но файлы {where}не разбираются:\n"
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
                #
                # И не снимаем тревогу о структуре. Раньше здесь стоял
                # clear с текстом «Файлы снова разбираются», хотя ничего
                # не разбиралось: сеть упала, структура сломана, а админ
                # получал «восстановилось». На мигающем сайте это давало
                # «проблема → восстановилось → проблема» каждый цикл.
                logging.info("сетевой сбой, тревога о структуре остаётся: %s",
                             _short(error))
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


async def _report_parse_failure(bot, repo: RequestsRepo, config: Config,
                                parse_failed: list[str]) -> None:
    """Файлы скачались, но не разобрались — это работа для человека.

    Отличается от частичного сбоя: 404 может пройти сам, если файл
    вернут на место, а сломанную структуру правит только человек.
    Поэтому тревога другая, и ключ другой.
    """
    names = ", ".join(parse_failed)
    try:
        await alerts.alert(
            bot, repo, config, "structure",
            f"Файлы скачиваются, но не разбираются: <code>{names}</code>\n\n"
            f"Скорее всего изменилась структура файла. Расписание работает "
            f"на последних данных, но новые правки не подтягиваются — "
            f"это само не пройдёт, нужен разбор парсера.",
        )
    except Exception:
        logging.exception("не удалось отправить тревогу о структуре")


# Раз в сутки чистим прошедшие дни. Материализация идёт только вперёд,
# поэтому старые даты не перезаписываются никогда и копятся навсегда
# (на проде 27.10 — 1434 строки из 4359). История уже в day_snapshot.
_purge = {"date": None}


async def _purge_past(session_pool, today: datetime.date | None = None) -> None:
    today = today or datetime.date.today()
    if today == _purge["date"]:
        return
    _purge["date"] = today
    try:
        async with session_pool() as db:
            repo = RequestsRepo(db)
            removed = await repo.college_lessons.delete_before(today)
            # Замены старше вчерашнего дня не нужны никому: редактор
            # показывает ровно «вчера..+6», рассылка идёт по college_lesson.
            # На проде 27.10 их было 201 из 256.
            stale_subs = await repo.substitutions.delete_before(
                today - datetime.timedelta(days=1))
        if removed:
            logging.info("college_lesson: удалено %d прошедших пар", removed)
        if stale_subs:
            logging.info("substitution: удалено %d прошедших замен", stale_subs)
    except Exception:
        # Не считаем день отработанным: повторим на следующем проходе.
        _purge["date"] = None
        logging.exception("не удалось почистить прошедшие пары")


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
        except Exception as e:
            # Сбой вуза раньше писал только строку в лог. Колледж в том
            # же цикле зовёт _report_failure: сломанная структура сама не
            # починится, и человек должен узнать.
            logging.warning("синхронизация вуза не удалась: %s", e)
            await _report_failure(bot, session_pool, config, e)

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
            parse_failed = set(result.get("parse_failed") or [])
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
                # Сломанная структура — единственное, что само не
                # пройдёт. До этой правки parse-сбой расписания и замен
                # глотался в _step и до тревоги не доходил: админ видел
                # только «сайт не отвечает», хотя сайт жив.
                if parse_failed:
                    await _report_parse_failure(bot, repo, config, sorted(parse_failed))
                elif not failed:
                    # Разбор прошёл на всех файлах — вот теперь тревогу
                    # можно снимать. Раньше её снимал сетевой сбой.
                    await alerts.clear(bot, repo, config, "structure",
                                       "Файлы снова разбираются.")

        # Материализуем ВСЕГДА, даже при сбое сайта и даже если файлы не
        # менялись: окно дат должно сдвигаться вперёд каждый день, иначе
        # через две недели расписание «кончится» — файлы те же, а новых
        # дат в college_lesson нет. Слои при сбое целы, так что
        # материализация соберёт те же данные на новые даты.
        async with session_pool() as db:
            repo = RequestsRepo(db)
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

        # «Новое» — это день, которого в базе не было ДО материализации.
        # Раньше здесь стояло `had_lessons == 0` — общее число пар во всей
        # таблице, без привязки к дате. На непустой базе (3927 строк) оно
        # неверно никогда, и студент вместо «🆕 Новое расписание» всегда
        # видел «🔄 Изменилось», даже в первый день семестра.
        for date in sorted(changed):
            changes.append((date, date not in before, changed[date]))
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
        # Одно фото на день для всех. Раньше random_photo звался на каждого
        # подписчика и делал os.listdir — 3080 чтений диска при 14 датах,
        # и каждый получал свою картинку за один и тот же день.
        day_photo = photos.random_photo(photos_path, weekday)
        prefix = "🆕 <b>Новое расписание</b>\n\n" if is_new else "🔄 <b>Расписание изменилось</b>\n\n"
        for user in subscribers:
            # Без группы и без фамилии искать нечего: get_for_group_date(None)
            # даёт «WHERE "group" IS NULL» — пусто, и человек получает
            # «Занятий нет 🙌» на каждую дату. Он подписан, но ни на что;
            # молчим, пока он не выберет группу или не назовётся.
            is_teacher = user.role == "teacher"
            if is_teacher and not user.teacher_name:
                continue
            if not is_teacher and not user.group:
                continue
            # Будить только тех, чья группа (или чьи пары) поменялась.
            # Пустой набор — «не знаем, что именно», тогда шлём всем.
            if groups:
                if not is_teacher and user.group not in groups:
                    continue
            async with session_pool() as db:
                repo = RequestsRepo(db)
                if is_teacher:
                    lessons = await repo.college_lessons.get_for_teacher_date(user.teacher_name, date)
                else:
                    lessons = await repo.college_lessons.get_for_group_date(user.group, date)
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
                    # Тот же флаг, что на экране дня и недели: иначе
                    # преподаватель на потоке получает шесть одинаковых
                    # строк в рассылке и одну на экране.
                    merge_groups=is_teacher,
                )
            else:
                text = format_no_lessons(date)
            photo = day_photo if (user.send_image and not is_teacher) else None
            items.append((user.id, prefix + text, photo))
        for chat in chats:
            if not chat.group:
                continue
            async with session_pool() as db:
                repo = RequestsRepo(db)
                lessons = await repo.college_lessons.get_for_group_date(chat.group, date)
            if lessons:
                text = format_day(date, lessons, bell, lunches, "brief")
            else:
                text = format_no_lessons(date)
            items.append((chat.id, prefix + text, day_photo))

    await broadcast_schedule(bot, items, rate=rate)


# Логика ночного окна живёт в source_state: порог устаревания должен
# знать то же окно, иначе ночью он объявляет сбой там, где его нет.
_in_night = source_state.in_night


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
            await _purge_past(session_pool)

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
