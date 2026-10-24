"""Синхронизация расписания вуза из файлов `.xls` на norvuz.ru.

Отдельно от ``sync_eios``: у вуза другой источник, другой формат и другая
модель хранения (недели списком). Общее у них — только таблицы.

Файлы:

* ``1-ochnoe.xls``         — очная, бакалавриат и специалитет
* ``2-ochno-zaochnoe.xls`` — очно-заочная

Заочную (``3-zaochnoe.xls``) пока не берём — по решению владельца
отложена.

Синхронизация идемпотентна: файл скачивается, сравнивается по хешу, и
если он не менялся — ничего не пишется. Это важно, потому что поллер
ходит раз в 10 минут, а файл обновляется раз в сутки.
"""

from __future__ import annotations

import asyncio
import datetime
import hashlib
import logging

from aiohttp import ClientSession
from sqlalchemy import delete, select

from infrastructure.database.models import BaseLesson, VuzGroup
from infrastructure.database.repo.requests import RequestsRepo
from parsers import vuz

log = logging.getLogger(__name__)

SOURCE_SITE = "site"
SOURCE_VUZ = "vuz"

# Какой файл какой форме обучения соответствует.
FILES = {
    "full": f"{vuz.BASE_URL}/1-ochnoe.xls",
    "part": f"{vuz.BASE_URL}/2-ochno-zaochnoe.xls",
}

_HASH_KEY = "vuz_hash_{form}"
ANCHOR_KEY = "vuz_week_anchor"

# Якорь по умолчанию: 31.08.2026 — первая неделя. Сверено на 38
# датированных ячейках файла (35 совпадений).
DEFAULT_ANCHOR = datetime.date(2026, 8, 31)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def weeks_to_str(weeks: tuple[int, ...]) -> str:
    """Недели в строку для колонки: (6,8,10) -> "6,8,10"."""
    return ",".join(str(w) for w in weeks)


def str_to_weeks(raw: str) -> tuple[int, ...]:
    return tuple(int(w) for w in raw.split(",") if w.strip().isdigit())


def vuz_week(date: datetime.date, anchor: datetime.date | None = None) -> int:
    """Номер учебной недели вуза для даты.

    Считается от якоря: неделя якоря — первая. У вуза своя нумерация,
    она не совпадает с чётностью колледжа.
    """
    anchor = anchor or DEFAULT_ANCHOR
    return (date - anchor).days // 7 + 1


# --- запись в базу -----------------------------------------------------------

async def replace_vuz_lessons(
    repo: RequestsRepo, lessons: list[vuz.VuzLesson], form: str,
) -> int:
    """Заменить базовое расписание вуза для одной формы обучения.

    Перезаписываем целиком, как и у колледжа: файл содержит весь семестр,
    и «хвосты» от прошлой версии (убрали пару) иначе останутся висеть.

    Важно: чистим только строки своей формы. Очная и очно-заочная лежат
    в одной таблице, и общий delete снёс бы чужой файл — так и случилось
    на первом прогоне: после второго файла осталась только очно-заочная.

    Ручные правки (``source != 'vuz'``) сохраняются.
    """
    # Группы своей формы: справочник vuz_group знает, кто к какой относится.
    own_groups = [
        g for (g,) in await repo.session.execute(
            select(VuzGroup.name).where(VuzGroup.form == form)
        )
    ]
    own = set(own_groups)

    manual = [
        row for (row,) in await repo.session.execute(
            select(BaseLesson).where(
                BaseLesson.source != SOURCE_VUZ,
                BaseLesson.group.like(f"%{vuz.VUZ_SUFFIX}"),
            )
        )
    ]
    manual_keys = {(r.group, r.week_parity, r.weekday, r.para, r.weeks or "")
                   for r in manual}

    # Чистим только свою форму. Если справочника ещё нет (первый запуск),
    # берём группы из самого файла.
    if own:
        await repo.session.execute(
            delete(BaseLesson).where(
                BaseLesson.source == SOURCE_VUZ,
                BaseLesson.group.in_(own),
            )
        )
    else:
        await repo.session.execute(
            delete(BaseLesson).where(
                BaseLesson.source == SOURCE_VUZ,
                BaseLesson.group.like(f"%{vuz.VUZ_SUFFIX}"),
            )
        )

    now = datetime.datetime.now()
    seen: set[tuple] = set()
    added = 0
    for lesson in lessons:
        weeks = weeks_to_str(lesson.weeks)
        key = (lesson.group, lesson.parity, lesson.weekday, lesson.para, weeks)
        if key in seen:
            log.warning("дубль в расписании вуза: %s", key)
            continue
        if key in manual_keys:
            continue
        seen.add(key)
        repo.session.add(
            BaseLesson(
                group=lesson.group,
                week_parity=lesson.parity,
                weekday=lesson.weekday,
                para=lesson.para,
                weeks=weeks,
                subject=(lesson.subject or "")[:256],
                teacher=(lesson.teacher or "")[:128],
                room=(lesson.room or "")[:64],
                source=SOURCE_VUZ,
                updated_at=now,
            )
        )
        added += 1

    await repo.session.commit()
    return added + len(manual)


async def replace_vuz_groups(
    repo: RequestsRepo, groups: list[vuz.VuzGroup], form: str,
) -> int:
    """Обновить справочник групп вуза для одной формы обучения.

    Нужен для навигации: студент выбирает факультет, потом курс, потом
    группу. По имени группы факультет не определить.

    Чистим только свою форму: очная и очно-заочная живут в одной таблице.
    """
    await repo.session.execute(delete(VuzGroup).where(VuzGroup.form == form))
    for group in groups:
        repo.session.add(
            VuzGroup(
                name=group.name,
                faculty=group.faculty,
                course=group.course,
                form=group.form,
            )
        )
    await repo.session.commit()
    return len(groups)


async def replace_vuz_changes(
    repo: RequestsRepo, changes: list[vuz.VuzChange], form: str,
) -> int:
    """Записать замены, найденные внутри файла расписания.

    У вуза отдельного листка замен нет: замены и переносы стоят прямо
    в клетках с датой. Пишем их в ту же таблицу, что и колледж, чтобы
    показ и уведомления работали одинаково.

    Чистим только группы своей формы: иначе второй файл сносит замены
    первого — та же ошибка, что была с уроками.
    """
    from infrastructure.database.models import Substitution

    if not changes:
        return 0

    own_groups = [
        g for (g,) in await repo.session.execute(
            select(VuzGroup.name).where(VuzGroup.form == form)
        )
    ]

    manual = [
        row for (row,) in await repo.session.execute(
            select(Substitution).where(Substitution.source != SOURCE_VUZ)
        )
    ]
    manual_keys = {(r.date, r.group, r.para) for r in manual}

    if own_groups:
        await repo.session.execute(
            delete(Substitution).where(
                Substitution.source == SOURCE_VUZ,
                Substitution.group.in_(own_groups),
            )
        )
    else:
        await repo.session.execute(
            delete(Substitution).where(Substitution.source == SOURCE_VUZ)
        )

    now = datetime.datetime.now()
    seen: set[tuple] = set()
    added = 0
    for change in changes:
        if change.para is None:
            continue
        key = (change.date, change.group, change.para)
        if key in seen or key in manual_keys:
            continue
        seen.add(key)
        repo.session.add(
            Substitution(
                date=change.date,
                group=change.group,
                para=change.para,
                action=change.action,
                subject=(change.subject or "")[:256],
                teacher=(change.teacher or "")[:128],
                room=(change.room or "")[:64],
                comment="",
                source=SOURCE_VUZ,
                created_at=now,
            )
        )
        added += 1

    await repo.session.commit()
    return added + len(manual)


# --- якорь недели ------------------------------------------------------------

async def get_anchor(repo: RequestsRepo) -> datetime.date:
    """Якорь учебной недели вуза из настроек."""
    raw = await repo.settings.get(ANCHOR_KEY)
    if raw:
        try:
            return datetime.date.fromisoformat(raw)
        except ValueError:
            log.warning("якорь недели вуза испорчен: %r", raw)
    return DEFAULT_ANCHOR


async def set_anchor(repo: RequestsRepo, value: datetime.date) -> None:
    await repo.settings.set(ANCHOR_KEY, value.isoformat())


# --- скачивание --------------------------------------------------------------

async def _download(session: ClientSession, url: str) -> bytes:
    async with session.get(url) as response:
        response.raise_for_status()
        return await response.read()


async def sync_once(
    session: ClientSession,
    repo: RequestsRepo,
    *,
    force: bool = False,
) -> dict:
    """Один проход синхронизации вуза.

    Возвращает ``{"full": bool, "part": bool, "groups": int, "failed": [...]}``.
    """
    result = {"full": False, "part": False, "groups": 0, "failed": []}
    all_groups: list[vuz.VuzGroup] = []

    for form, url in FILES.items():
        try:
            data = await _download(session, url)
        except Exception as exc:  # noqa: BLE001
            log.warning("не удалось скачать %s: %s", url, exc)
            result["failed"].append(form)
            continue

        digest = _sha(data)
        key = _HASH_KEY.format(form=form)
        if not force and await repo.settings.get(key) == digest:
            continue

        try:
            parsed = await asyncio.to_thread(vuz.parse, data, form)
        except vuz.VuzParseError as exc:
            # Структура файла поменялась — это не сетевой сбой, и молчать
            # нельзя: студенты увидят устаревшее расписание.
            log.error("файл вуза %s не разобрался: %s", form, exc)
            result["failed"].append(form)
            raise

        # Справочник пишем первым: replace_vuz_lessons по нему понимает,
        # какие группы относятся к этой форме, и не сносит чужой файл.
        await replace_vuz_groups(repo, parsed.groups, form)
        count = await replace_vuz_lessons(repo, parsed.lessons, form)
        await replace_vuz_changes(repo, parsed.changes, form)
        await repo.settings.set(key, digest)
        log.info("расписание вуза (%s) обновлено: %d пар, %d замен",
                 form, count, len(parsed.changes))
        result[form] = True
        all_groups.extend(parsed.groups)

    result["groups"] = len(all_groups)
    return result
