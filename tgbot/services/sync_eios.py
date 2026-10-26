"""Синхронизация расписания СПО из ЭИОС в базу.

Скачивает файлы колледжа (очное расписание, листок замен, звонки), разбирает
их и раскладывает в слои ``base_lesson`` + ``substitution``.

Дедуп — по содержимому (sha256): файлы перезаписываются по одному и тому же
URL, поэтому ETag и Last-Modified ненадёжны.
"""

from __future__ import annotations

import asyncio
import datetime
import hashlib
import logging

from aiohttp import ClientSession
from sqlalchemy import delete, select

from common.schedule import PARITY_ANY, PARITY_EVEN, PARITY_ODD, VUZ_GROUP
from config import Config
from infrastructure.database.models import BaseLesson, BellSchedule, Substitution
from infrastructure.database.repo.requests import RequestsRepo
from parsers import eios
from tgbot.services.schedule_layer import get_day_slots
from parsers.eios import (
    PARITY_BOTH,
    PARITY_EVEN as PARSER_EVEN,
    PARITY_ODD as PARSER_ODD,
    BaseLesson as ParsedLesson,
    Substitution as ParsedSub,
)

log = logging.getLogger(__name__)

SOURCE_SITE = "site"
_HASH_KEY = "eios_hash_{kind}"

# Имена шагов в ``sync_once``. Вынесены в константы, потому что по ним
# поллер отличает «сайт лёг» от «один файл убрали»: сравнивает failed
# с attempted.
STEP_OCHOE = "очное расписание"
STEP_ZAMENY = "замены"
STEP_BELLS = "звонки"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def db_parity(parsed: str) -> str:
    """Чётность парсера → чётность в БД.

    Парсер: ``BOTH`` / ``EVEN`` / ``ODD``.  БД: ``ANY`` / ``EVEN`` / ``ODD``.
    """
    return {
        PARITY_BOTH: PARITY_ANY,
        PARSER_EVEN: PARITY_EVEN,
        PARSER_ODD: PARITY_ODD,
    }.get(parsed, PARITY_ANY)


# --- загрузка слоёв ----------------------------------------------------------

async def replace_base_lessons(repo: RequestsRepo, lessons: list[ParsedLesson]) -> int:
    """Заменить базовое расписание, пришедшее с сайта.

    Файл содержит весь семестр целиком, поэтому перезаписываем: иначе остались
    бы «хвосты» от прошлой версии (например, убранная из расписания пара).
    Ручные правки (``source != 'site'``) сохраняются.
    """
    manual = [
        row
        for (row,) in await repo.session.execute(
            select(BaseLesson).where(BaseLesson.source != SOURCE_SITE)
        )
    ]
    # Ручная правка важнее сайта: её слот не должен достаться данным из файла,
    # иначе на одно (group, parity, weekday, para) будет две строки и UNIQUE
    # упадёт с IntegrityError. Сами ручные строки не трогаем — delete ниже
    # сносит только source='site'.
    manual_keys = {(r.group, r.week_parity, r.weekday, r.para) for r in manual}

    await repo.session.execute(delete(BaseLesson).where(BaseLesson.source == SOURCE_SITE))

    now = datetime.datetime.now()
    seen: set[tuple[str, str, int, int]] = set()
    added = 0
    for lesson in lessons:
        parity = db_parity(lesson.parity)
        key = (lesson.group, parity, lesson.day, lesson.para)
        if key in seen:
            log.warning("дубль в базовом расписании: %s", key)
            continue
        if key in manual_keys:
            # Здесь уже есть ручная правка — не перетираем её.
            continue
        seen.add(key)
        repo.session.add(
            BaseLesson(
                group=lesson.group,
                week_parity=parity,
                weekday=lesson.day,
                para=lesson.para,
                subject=(lesson.subject or "")[:128],
                teacher=(lesson.teacher or "")[:128],
                room="",
                source=SOURCE_SITE,
                updated_at=now,
            )
        )
        added += 1

    await repo.session.commit()
    return added + len(manual)


async def replace_substitutions(repo: RequestsRepo, subs: list[ParsedSub]) -> int:
    """Заменить замены, пришедшие с сайта. Ручные не трогаем."""
    manual = [
        row
        for (row,) in await repo.session.execute(
            select(Substitution).where(Substitution.source != SOURCE_SITE)
        )
    ]
    # Как и в базовом расписании: ручная замена на том же слоте не должна
    # конфликтовать с пришедшей с сайта (UNIQUE по date+group+para).
    manual_keys = {(r.date, r.group, r.para) for r in manual}

    await repo.session.execute(
        delete(Substitution).where(Substitution.source == SOURCE_SITE)
    )

    now = datetime.datetime.now()
    seen: set[tuple[datetime.date, str, int]] = set()
    added = 0
    for sub in subs:
        key = (sub.date, sub.group, sub.para)
        if key in seen or key in manual_keys:
            continue
        seen.add(key)
        repo.session.add(
            Substitution(
                date=sub.date,
                group=sub.group,
                para=sub.para,
                action=sub.action,
                subject=(sub.subject or "")[:128],
                teacher=(sub.teacher or "")[:128],
                room=(sub.room or "")[:64],
                comment=(sub.raw_now or "")[:256],
                source=SOURCE_SITE,
                created_at=now,
            )
        )
        added += 1

    await repo.session.commit()
    return added + len(manual)


async def replace_bells(repo: RequestsRepo, slots: list[eios.BellSlot]) -> int:
    """Заменить расписание звонков целиком.

    Сохраняем строки, которые приходят не из файлов колледжа:
    ``ALL`` — «Разговоры о важном», ``VUZ`` — сетка вуза (8 пар).
    Их удаление снесло бы чужие данные при первом же проходе.
    """
    keep = ("ALL", VUZ_GROUP)
    special = [
        row
        for (row,) in await repo.session.execute(
            select(BellSchedule).where(BellSchedule.course_group.in_(keep))
        )
    ]
    await repo.session.execute(
        delete(BellSchedule).where(BellSchedule.course_group.notin_(keep))
    )

    for slot in slots:
        repo.session.add(
            BellSchedule(
                day_type=slot.day_type,
                course_group=slot.course_group,
                para=slot.para,
                start=slot.start,
                h1_end=slot.end1,
                h2_start=slot.start2,
                end=slot.end2,
            )
        )

    for row in special:
        repo.session.add(row)

    await repo.session.commit()
    return len(slots) + len(special)


# --- скачивание --------------------------------------------------------------

async def _download(session: ClientSession, url: str) -> bytes:
    async with session.get(url, raise_for_status=True, timeout=60) as response:
        return await response.read()


async def _fetch_links(session: ClientSession, config: Config) -> eios.SourceLinks:
    html = await _download(session, config.schedule_url)
    return eios.extract_links(html.decode("utf-8", errors="replace"))


def _resolve_groups(subs: list[ParsedSub], known: list[str]) -> list[ParsedSub]:
    """Привести имена групп из листка замен к именам из расписания.

    В листке встречаются ``ЭОК-26`` (регистр), ``ДОУ - 25`` (пробелы) и
    ``ЭОф-26`` (опечатка вместо ``ЭО-26ФП``).
    """
    resolved: list[ParsedSub] = []
    warned: set[str] = set()
    for sub in subs:
        name = eios.match_group(sub.group, known)
        if name is None:
            if sub.group not in warned:
                log.warning("группа из листка замен не найдена: %r", sub.group)
                warned.add(sub.group)
            continue
        sub.group = name
        resolved.append(sub)
    return resolved


# --- основной проход ---------------------------------------------------------

async def sync_once(
    session: ClientSession,
    repo: RequestsRepo,
    config: Config,
    *,
    force: bool = False,
) -> dict[str, bool]:
    """Один проход синхронизации.

    Возвращает, что изменилось: ``{"ochoe": bool, "zameny": bool, "bells": bool}``,
    плюс ``failed`` (имена упавших шагов) и ``attempted`` (имена
    запрошенных). По ним поллер отличает «сайт лёг» от «один файл убрали».
    """
    changed = {"ochoe": False, "zameny": False, "bells": False}
    links = await _fetch_links(session, config)
    failed: list[str] = []
    parse_failed: list[str] = []
    attempted: list[str] = []

    # Каждый файл обновляем независимо: если листок замен вернул 404,
    # звонки всё равно должны обновиться. Иначе один битый файл из трёх
    # останавливает весь проход и сайт выглядит «лежащим», хотя он жив.
    #
    # Отдельно копим parse_failed: сеть восстановится сама, а сломанная
    # структура файла — нет. Только она заслуживает тревоги «нужен
    # человек», и только её нельзя путать с сетевым сбоем.
    async def _step(name: str, coro) -> None:
        attempted.append(name)
        try:
            await coro
        except eios.EiosParseError as exc:
            log.warning("не разобрался %s: %s", name, exc)
            failed.append(name)
            parse_failed.append(name)
        except Exception as exc:  # noqa: BLE001
            log.warning("не удалось обновить %s: %s", name, exc)
            failed.append(name)

    # --- базовое расписание ---
    if links.ochoe:
        await _step(STEP_OCHOE, _sync_ochoe(session, repo, links.ochoe, force, changed))

    # --- замены ---
    if links.zameny:
        await _step(STEP_ZAMENY, _sync_zameny(session, repo, links.zameny, force, changed))

    # --- звонки ---
    if links.bells_monday or links.bells_standard:
        await _step(STEP_BELLS, _sync_bells(session, repo, links, force, changed))

    if failed:
        changed["failed"] = failed
    # Сломанная структура файла: сама не починится, нужен человек.
    # Отдельным ключом, чтобы не менять формат failed — его читает поллер.
    if parse_failed:
        changed["parse_failed"] = parse_failed
    # Какие шаги вообще пробовали. Без этого «упали все» не отличить от
    # «половину файлов убрали со страницы»: непробованный шаг не попадает
    # ни в failed, ни в успех, и сравнение с ALL_STEPS врёт.
    changed["attempted"] = attempted
    return changed


async def _sync_bells(session, repo, links, force: bool, changed: dict) -> None:
    """Звонки: два файла (понедельник и обычный) в одну таблицу.

    Отдельной функцией, а не блоком в ``sync_once``: иначе падение
    звонков вылетает из прохода целиком, ``sync_once`` бросает
    исключение, и уже записанное очное расписание теряет отметку
    свежести — студент видит «сайт не отвечает», хотя сайт жив.
    """
    slots = []
    if links.bells_monday:
        data = await _download(session, links.bells_monday)
        slots += await asyncio.to_thread(eios.parse_bells, data, "MONDAY")
    if links.bells_standard:
        data = await _download(session, links.bells_standard)
        slots += await asyncio.to_thread(eios.parse_bells, data, "OTHER")
    if not slots:
        return
    digest = hashlib.sha256(
        repr(sorted(
            (s.day_type, s.course_group, s.para, str(s.start), str(s.end2))
            for s in slots
        )).encode()
    ).hexdigest()
    if force or await repo.settings.get(_HASH_KEY.format(kind="bells")) != digest:
        count = await replace_bells(repo, slots)
        await repo.settings.set(_HASH_KEY.format(kind="bells"), digest)
        log.info("звонки обновлены: %d слотов", count)
        changed["bells"] = True


async def _sync_ochoe(session, repo, url: str, force: bool, changed: dict) -> None:
    data = await _download(session, url)
    digest = _sha(data)
    if force or await repo.settings.get(_HASH_KEY.format(kind="ochoe")) != digest:
        lessons = await asyncio.to_thread(eios.parse_ochoe, data)
        count = await replace_base_lessons(repo, lessons)
        await repo.settings.set(_HASH_KEY.format(kind="ochoe"), digest)
        log.info("базовое расписание обновлено: %d пар", count)
        changed["ochoe"] = True


async def _sync_zameny(session, repo, url: str, force: bool, changed: dict) -> None:
    data = await _download(session, url)
    digest = _sha(data)
    if force or await repo.settings.get(_HASH_KEY.format(kind="zameny")) != digest:
        subs = await asyncio.to_thread(eios.parse_substitutions, data)
        known = await repo.base_lessons.get_groups()
        subs = _resolve_groups(subs, known)
        count = await replace_substitutions(repo, subs)
        await repo.settings.set(_HASH_KEY.format(kind="zameny"), digest)
        log.info("замены обновлены: %d записей", count)
        changed["zameny"] = True


# --- материализация слоёв в college_lesson ----------------------------------

MATERIALIZE_DAYS = 14


def _merge_para_clash(slots: list) -> list:
    """Склеить пары, оказавшиеся на одном номере.

    У вуза бывает, что на одну пару приходятся два предмета: физкультура
    идёт потоком все недели, а иностранный язык — по подгруппам на
    отдельных. В ``college_lesson`` уникален ключ (дата, группа, пара),
    поэтому две строки туда не влезут. Показываем обе через « / »:
    студент увидит, что в это время у него два варианта.

    ponytail: склейка теряет структуру (какой предмет чей). Если вуз
    начнёт делить группы по подгруппам всерьёз — нужна колонка subgroup.
    """
    from tgbot.services.schedule_layer import Slot

    seen: dict[int, Slot] = {}
    for slot in slots:
        prev = seen.get(slot.para)
        if prev is None:
            seen[slot.para] = slot
            continue
        subjects = {prev.subject, slot.subject}
        if len(subjects) == 1:
            continue
        seen[slot.para] = Slot(
            para=slot.para,
            subject=f"{prev.subject} / {slot.subject}"[:256],
            teacher=f"{prev.teacher} / {slot.teacher}"[:128] if prev.teacher or slot.teacher else "",
            room=prev.room or slot.room,
            changed=prev.changed or slot.changed,
            action=prev.action or slot.action,
            comment=prev.comment,
        )
    return [seen[p] for p in sorted(seen)]


async def materialize_day(repo: RequestsRepo, date: datetime.date) -> int:
    """Пересобрать один день в ``college_lesson``.

    Нужно после ручной правки: студент читает готовую таблицу, а не
    слои, поэтому без пересборки замена появлялась у него только после
    следующего опроса — до пяти минут, а если сайт лежал, то никогда.
    """
    from infrastructure.database.models import CollegeLesson

    manual = [
        row
        for (row,) in await repo.session.execute(
            select(CollegeLesson).where(
                CollegeLesson.date == date,
                CollegeLesson.source != SOURCE_SITE,
            )
        )
    ]
    manual_keys = {(r.group, r.para) for r in manual}
    rows: list[dict] = [
        {
            "date": r.date, "group": r.group, "para": r.para,
            "para_end": r.para_end, "subject": r.subject,
            "teacher": r.teacher, "room": r.room,
            "source_url": r.source_url, "source": r.source,
            "changed": r.changed, "action": r.action,
        }
        for r in manual
    ]
    for group in await repo.base_lessons.get_groups():
        slots = await get_day_slots(repo, group, date)
        for slot in _merge_para_clash(slots):
            if (group, slot.para) in manual_keys:
                continue
            rows.append({
                "date": date,
                "group": group,
                "para": slot.para,
                "para_end": slot.para,
                "subject": (slot.subject or "")[:256],
                "teacher": (slot.teacher or "")[:128],
                "room": (slot.room or "")[:64],
                "source_url": "",
                "source": SOURCE_SITE,
                "changed": slot.changed,
                "action": slot.action or "",
            })
    await repo.college_lessons.replace_date(date, rows)
    return len(rows)


async def materialize(repo: RequestsRepo, days: int = MATERIALIZE_DAYS) -> int:
    """Собрать итоговое расписание из слоёв и положить в ``college_lesson``.

    Зачем: почти весь код бота (хендлеры, поллер, звонки) читает готовую
    таблицу ``college_lesson`` по дате. Слои ``base_lesson`` + ``substitution``
    — источник истины, но чтобы не переписывать два десятка мест разом,
    раскладываем результат на ближайшие дни. Ручные правки старосты
    (``source='manual'``) при этом сохраняются.

    Возвращает число дней, которые были записаны.
    """
    from infrastructure.database.models import CollegeLesson

    today = datetime.date.today()
    groups = await repo.base_lessons.get_groups()
    written = 0

    for offset in range(days):
        date = today + datetime.timedelta(days=offset)
        # Ручные правки старосты важнее данных с сайта: их слоты не заполняем
        # сгенерированными парами, а сами строки переносим как есть.
        manual = [
            row
            for (row,) in await repo.session.execute(
                select(CollegeLesson).where(
                    CollegeLesson.date == date,
                    CollegeLesson.source != SOURCE_SITE,
                )
            )
        ]
        manual_keys = {(r.group, r.para) for r in manual}

        rows: list[dict] = [
            {
                "date": r.date, "group": r.group, "para": r.para,
                "para_end": r.para_end, "subject": r.subject,
                "teacher": r.teacher, "room": r.room,
                "source_url": r.source_url, "source": r.source,
                "changed": r.changed, "action": r.action,
            }
            for r in manual
        ]
        for group in groups:
            slots = await get_day_slots(repo, group, date)
            for slot in _merge_para_clash(slots):
                if (group, slot.para) in manual_keys:
                    continue
                rows.append({
                    "date": date,
                    "group": group,
                    "para": slot.para,
                    "para_end": slot.para,
                    "subject": (slot.subject or "")[:256],
                    "teacher": (slot.teacher or "")[:128],
                    "room": (slot.room or "")[:64],
                    "source_url": "",
                    "source": SOURCE_SITE,
                    "changed": slot.changed,
                    "action": slot.action or "",
                })

        await repo.college_lessons.replace_date(date, rows)
        written += 1

        # Расписание пришло с сайта — значит день опубликован. Раньше
        # schedule_file заполнял старый парсер, после перехода на ЭИОС её
        # перестали обновлять, и студент на пустой день видел «не выложено».
        if await repo.schedule_files.get_hash(date) is None:
            await repo.schedule_files.set_hash(date, f"eios-{date.isoformat()}")

    log.info("материализовано %d дней в college_lesson", written)
    return written
