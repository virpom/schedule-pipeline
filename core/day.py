"""Экран дня: решить, ЧТО показать, не решая, КАК это выглядит.

Раньше это была одна функция `_day_text` в `tgbot/handlers/user.py`:
она ходила в базу, разбиралась с пятью состояниями дня и тут же
склеивала HTML-строку. Второй бот (MAX) не смог бы этим
воспользоваться — пришлось бы копировать 113 строк вместе с разметкой.

Теперь разделено:

* здесь — сбор данных и выбор состояния (`DayView`);
* в `core/render.py` — превращение в текст.

Разделение не косметическое: состояния дня — это предметная логика
(«сайт лежит, но расписание верное» против «не знаем, есть ли пары»),
а теги `<b>` — оформление.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass, field

from common.schedule import SUB_CANCEL, is_vuz
from core import source_state
from core.schedule_layer import get_day_slots
from infrastructure.database.models import User
from infrastructure.database.repo.requests import RequestsRepo

# Сколько дней вперёд искать «Ближайшее», когда сегодня пар нет.
NEAREST_DAYS = 7


@dataclass
class DayView:
    """Всё, что нужно, чтобы нарисовать экран дня.

    ``state`` — почему экран выглядит именно так. Рендерер по нему
    выбирает текст, а тесты — проверяют ветку, не сравнивая строки.
    """

    date: datetime.date
    state: str
    lessons: list = field(default_factory=list)
    nearest: tuple[datetime.date, list] | None = None
    stale_when: datetime.datetime | None = None
    identity_missing: bool = False

    # Состояния. Строки, а не Enum: их видно в логах и тестах как есть.
    NO_IDENTITY = "no_identity"      # группа/фамилия не выбрана
    LESSONS = "lessons"              # есть пары
    CANCELLED = "cancelled"          # пары есть, но все отменены
    NOT_PUBLISHED = "not_published"  # дня нет ни в расписании, ни в публикации
    NO_LESSONS = "no_lessons"        # день опубликован, пар нет
    UNVERIFIED = "unverified"        # пар нет И сайт недоступен — не знаем


def is_teacher(user: User) -> bool:
    return user.role == "teacher"


def has_identity(user: User) -> bool:
    """Выбрана ли группа (студент) или фамилия (преподаватель)."""
    if is_teacher(user):
        return bool((user.teacher_name or "").strip())
    return bool(user.group)


def _slot_is_his(slot, teacher_name: str) -> bool:
    from common.schedule import teacher_matches
    return teacher_matches(slot.teacher, teacher_name)


def _dedupe_slots(slots: list):
    """Одна пара — одна строка.

    Преподаватель в пяти группах давал пять одинаковых строк: format_day
    склеивает по точному совпадению предмета, а «(лек.)» и «(лек)» —
    разные ключи. Здесь ключ нормализован, а группы собираются подпись.
    """
    import re

    def key(s):
        return (s.para, s.para_end,
                re.sub(r"[\s.()]+", "", (s.subject or "")).lower(),
                (s.teacher or "").lower())

    merged: dict[tuple, object] = {}
    for s in slots:
        k = key(s)
        prev = merged.get(k)
        if prev is None:
            merged[k] = s
            continue
        groups = [g for g in (prev.group or "").split(", ") if g]
        if s.group and s.group not in groups:
            groups.append(s.group)
        prev.group = ", ".join(groups)
    return list(merged.values())


def _subj_key(item) -> str:
    """Предмет для сопоставления источников: «(лек.)» и «(лек)» — одно."""
    import re
    return re.sub(r"[\s.()]+", "", (item.subject or "")).lower()


def _drop_vuz_covered(college: list, vuz: list) -> list:
    """Убрать из college строки вуза, которые уже есть в vuz.

    college_lesson содержит и вузовские строки: материализация берёт все
    группы из base_lesson, включая @vuz. vuz_teacher_day читает тот же
    день через get_day_slots — с заменами и неделями. Складывая оба
    списка, получали каждую пару дважды: у Кабышевой 28.10 было 7 + 4,
    и все 4 — те же самые.

    Оставляем вузовскую версию: она учитывает замены, college_lesson —
    снимок материализации.
    """
    # Кабинет схлопываем до пустого: sources расходятся именно на нём —
    # в college_lesson он заполнен, в слое пуст (или номера не читаются).
    # Требуя точного совпадения, оставляли ту же пару дважды.
    covered = {(v.para, _subj_key(v)) for v in vuz}
    return [c for c in college
            if not (str(getattr(c, "group", "") or "").endswith("@vuz")
                    and (c.para, _subj_key(c)) in covered)]


async def vuz_teacher_day(repo: RequestsRepo, user: User,
                          date: datetime.date) -> list:
    """Пары преподавателя вуза на дату — через итоговый слой.

    Раньше читали base_lesson напрямую, и это давало две беды разом:
    замены вуза не применялись (их 160), а одна пара дублировалась по
    числу групп, где преподаватель ведёт, потому что ключ склейки в
    format_day требует точного совпадения предмета.

    Теперь идём по группам, где он ведёт пары в этот день, и берём
    get_day_slots — тот же путь, что у студента: с заменами, weeks и
    чётностью.
    """
    groups = await repo.base_lessons.get_teacher_groups(
        user.teacher_name, weekday=date.isoweekday())
    slots = []
    for group in groups:
        for slot in await get_day_slots(repo, group, date):
            # Преподаватель ведёт несколько групп: в чужой группе у него
            # могут быть только свои пары.
            if not _slot_is_his(slot, user.teacher_name):
                continue
            slot.date = date
            slots.append(slot)
    return _dedupe_slots(slots)


async def user_lessons(repo: RequestsRepo, user: User, date: datetime.date) -> list:
    """Пары пользователя на дату — студента или преподавателя."""
    if is_teacher(user):
        college = await repo.college_lessons.get_for_teacher_date(
            user.teacher_name, date)
        vuz = await vuz_teacher_day(repo, user, date)
        college = _drop_vuz_covered(college, vuz)
        return sorted([*college, *vuz], key=lambda l: l.para)
    return await repo.college_lessons.get_for_group_date(user.group, date)


async def course_group_map(repo: RequestsRepo, user: User) -> dict[str, str] | None:
    """Какой поток звонков у группы пользователя.

    Преподавателю нужен весь словарь: у него нет своей группы, а пары
    могут быть у групп разных курсов.
    """
    from common.schedule import bells_group

    if is_teacher(user):
        m = await repo.users.get_group_course_map()
        return m or None
    cg = bells_group(user.group, user.course)
    return {user.group: cg} if cg else None


async def _is_vuz_only_teacher(repo: RequestsRepo, user: User,
                               lessons: list) -> bool:
    """Ведёт ли преподаватель только вуз.

    is_vuz(None) — False, а у преподавателя group пуст всегда. Без этой
    проверки он получал предупреждение про сайт колледжа, даже если
    ведёт только вуз. Смотрим, откуда реально пришли его пары.
    """
    if not (is_teacher(user) and not user.group):
        return False
    groups = [str(getattr(l, "group", "") or "") for l in lessons]
    return bool(groups) and all(is_vuz(g) for g in groups)


async def build_day(repo: RequestsRepo, user: User,
                    date: datetime.date) -> DayView:
    """Собрать всё для экрана дня. Ни одного байта разметки."""
    if not has_identity(user):
        return DayView(date=date, state=DayView.NO_IDENTITY,
                       identity_missing=True)

    lessons = await user_lessons(repo, user, date)

    # Замены могли не доехать, если сайт лежит. Постоянное расписание при
    # этом верное, поэтому не скрываем его — только предупреждаем.
    # У вуза свой источник: сайт колледжа может лежать, а расписание вуза
    # при этом свежее. Общий флаг показывал студенту вуза чужую проблему.
    vuz_only = await _is_vuz_only_teacher(repo, user, lessons)
    if is_vuz(user.group) or vuz_only:
        stale = await source_state.is_stale_vuz(repo)
        last_ok = await source_state.last_ok_vuz(repo) if stale else None
    else:
        stale = await source_state.is_stale(repo)
        last_ok = await source_state.last_ok(repo) if stale else None

    # День из одних отмен — фактически день без пар. get_day_slots держит
    # отменённую пару, чтобы студент видел зачёркнутую строку, а не
    # «Занятий нет»; но «Ближайшее» от этого не должно пропадать: когда
    # пар нет целиком, знать, когда они будут, — самое нужное.
    all_cancelled = bool(lessons) and all(
        getattr(l, "action", "") == SUB_CANCEL for l in lessons)

    if lessons:
        state = DayView.CANCELLED if all_cancelled else DayView.LESSONS
    else:
        # Заметку из `no_lessons` больше не спрашиваем: писать в таблицу
        # некому. Её заполнял старый парсер, разбирая «Занятий нет» из
        # ячеек файла; после перехода на ЭИОС таких ячеек нет, и
        # replace_date не вызывается ниоткуда.
        published = await repo.schedule_files.get_hash(date) is not None
        if published:
            # День был опубликован — значит на момент публикации пар не было.
            state = DayView.NO_LESSONS
        elif stale:
            # Ни пары, ни публикации, ни связи с сайтом — утверждать
            # «занятий нет» нельзя.
            state = DayView.UNVERIFIED
        else:
            # `schedule_file` означает «день материализован», а не «сайт
            # выложил файл»: materialize пишет его на все 14 дней окна,
            # включая пустые. Для окна это одно и то же, за окном — нет.
            state = DayView.NOT_PUBLISHED

    # «Ближайшее» показываем, когда сегодня пар нет или все отменены.
    nearest = None
    if not lessons or all_cancelled:
        for i in range(1, NEAREST_DAYS + 1):
            d = date + datetime.timedelta(days=i)
            nxt = await user_lessons(repo, user, d)
            if nxt and not all(getattr(l, "action", "") == SUB_CANCEL
                               for l in nxt):
                nearest = (d, nxt)
                break

    return DayView(
        date=date,
        state=state,
        lessons=lessons,
        nearest=nearest,
        # Предупреждение показываем только если сайт уже опрашивался:
        # на свежем запуске пугать нечем.
        stale_when=last_ok if (stale and last_ok is not None) else None,
    )


async def user_lessons_range(repo: RequestsRepo, user: User,
                             start: datetime.date, end: datetime.date) -> list:
    """Пары пользователя за диапазон дат."""
    if is_teacher(user):
        rows = list(await repo.college_lessons.get_for_teacher_range(
            user.teacher_name, start, end))
        # Вуз в неделю не попадал вовсе: у преподавателя только с
        # вузовскими парами экран «Неделя» был пустым, хотя «Сегодня»
        # показывал шесть дней с парами.
        # Те же дубли, что и на экране дня: college_lesson для вуза и
        # vuz_teacher_day отдают одни и те же пары.
        vuz_rows = []
        day = start
        while day <= end:
            vuz_rows.extend(await vuz_teacher_day(repo, user, day))
            day += datetime.timedelta(days=1)
        rows = _drop_vuz_covered(rows, vuz_rows)
        return sorted([*rows, *vuz_rows], key=lambda l: (l.date, l.para))
    return await repo.college_lessons.get_for_group_range(user.group, start, end)


async def build_week(repo: RequestsRepo, user: User) -> tuple[list, bool]:
    """Дни недели для экрана «7 дней»: (entries, есть ли идентичность).

    Все семь дней, а не только те, где что-то есть. Раньше пустой день
    просто не попадал в entries, и студент не отличал «в этот день пар
    нет» от «этот день не показали». format_day на пустом списке сам
    рисует «Занятий нет».
    """
    if not has_identity(user):
        return [], False
    start = datetime.date.today()
    end = start + datetime.timedelta(days=6)
    lessons = await user_lessons_range(repo, user, start, end)
    by_date: dict[datetime.date, list] = {}
    for l in lessons:
        by_date.setdefault(l.date, []).append(l)
    entries = [(start + datetime.timedelta(days=i),
                by_date.get(start + datetime.timedelta(days=i), []))
               for i in range(7)]
    return entries, True
