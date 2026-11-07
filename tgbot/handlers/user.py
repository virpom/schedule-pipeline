import asyncio
import datetime
from types import SimpleNamespace

from aiogram import F, Router
from aiogram.exceptions import TelegramRetryAfter
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
                           KeyboardButton, Message, ReplyKeyboardMarkup)

from common.schedule import (
    BELL_FULL,
    BELL_LABELS,
    BELL_OFF,
    BELL_ORDER,
    BELL_START_END,
    DETAIL_LABELS,
    DETAIL_ORDER,
    VUZ_SUFFIX,
    bells_group,
    course_from_group,
    format_bell,
    format_day,
    format_teacher_results,
    is_vuz,
    strip_unit,
)
from core.day import (build_day, build_week, course_group_map,
                      is_teacher)
from core.menu import (college_pick_kb, menu_kb as build_menu_kb,
                       settings_kb as build_settings_kb,
                       teacher_letter_kb, teacher_search_kb,
                       teacher_unit_kb,
                       unit_kb, vuz_course_kb, vuz_faculty_kb,
                       vuz_form_kb, vuz_group_kb)
from core.render import render_day, render_week
from tgbot.adapters.keyboard import to_inline_kb
from infrastructure.database.models import User
from infrastructure.database.repo.requests import RequestsRepo

# Названия для людей: в базе коды, студенту они ничего не говорят.
FACULTY_NAMES = {
    "FEU": "⚡ ФЭЭиУ",
    "GTF": "⛏ ГТФ",
}
FORM_NAMES = {
    "full": "Очная",
    "part": "Очно-заочная",
}

user_router = Router()

BACK_KB = InlineKeyboardMarkup(
    inline_keyboard=[[InlineKeyboardButton(text="⬅️ В меню", callback_data="menu")]]
)

# С экрана дня и недели нужен путь к соседним дням: раньше оттуда был
# только «В меню», и переход «сегодня -> завтра» стоил двух нажатий
# через меню — на самое частое действие в боте.
NAV_KB = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="📅 Сегодня", callback_data="day:today"),
     InlineKeyboardButton(text="📅 Завтра", callback_data="day:tomorrow")],
    [InlineKeyboardButton(text="🗓 7 дней", callback_data="week")],
    [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu")],
])

ROLE_KB = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="🎓 Студент", callback_data="role:student")],
    [InlineKeyboardButton(text="👨‍🏫 Преподаватель", callback_data="role:teacher")],
])

UNIT_KB = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="🏫 Колледж", callback_data="unit:college")],
    [InlineKeyboardButton(text="🎓 Вуз", callback_data="unit:vuz")],
    [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu")],
])


class SubjectSearch(StatesGroup):
    waiting = State()


class TeacherSearch(StatesGroup):
    waiting = State()


def _is_teacher(user: User) -> bool:
    return user.role == "teacher"


def _has_identity(user: User) -> bool:
    return bool(user.teacher_name) if _is_teacher(user) else bool(user.group)


def _settings_text(user: User) -> str:
    """Экран настроек с примером того, что придёт при текущем режиме."""
    mode = user.bell_mode if user.bell_mode in BELL_PREVIEW else BELL_OFF
    return (f"⚙️ <b>Настройки</b>\n\n"
            f"Уведомления: <b>{BELL_LABELS.get(mode, 'выкл')}</b>\n"
            f"{BELL_PREVIEW[mode]}\n\n"
            f"Выбери действие 👇")

# Что именно придёт при каждом режиме. Показать пример дешевле, чем
# объяснять словами «звонок+конец пары» — человек не понимает разницу,
# пока не получит уведомление.
BELL_PREVIEW = {
    BELL_OFF: "<i>уведомления не приходят</i>",
    BELL_START_END: "🔔 1 пара · Математика · 204\n"
                    "🔔 Конец пары",
    BELL_FULL: "🔔 1 пара · Математика · 204\n"
               "🔔 Перемена\n"
               "🔔 Перемена закончилась\n"
               "🔔 Конец пары",
}


def _on_off(value: bool) -> str:
    return "вкл" if value else "выкл"


def menu_kb(user: User, support_link: str = "", is_editor: bool = False) -> InlineKeyboardMarkup:
    """Главное меню. Раскладка — в ядре, здесь только адаптер."""
    return to_inline_kb(build_menu_kb(user, support_link, is_editor))


def settings_kb(user: User) -> InlineKeyboardMarkup:
    """Настройки. Раскладка — в ядре."""
    return to_inline_kb(build_settings_kb(user))


def menu_text(user: User) -> str:
    if _is_teacher(user):
        if not (user.teacher_name or "").strip():
            return ("🎓 <b>Расписание ПТК</b>\n\n"
                    "Фамилия не выбрана.\n\nНайди себя в списке 👇")
        label, ident = "Преподаватель", user.teacher_name
    else:
        label = "Группа"
        # Суффикс @vuz — служебный, человеку его видеть незачем.
        if not user.group:
            # «не выбрана · 1 курс» читается как издевательство: курса
            # без группы не бывает, а кнопки дня всё равно откажут.
            return ("🎓 <b>Расписание ПТК</b>\n\n"
                    "Группа не выбрана.\n\nВыбери её, чтобы видеть расписание 👇")
        ident = strip_unit(user.group)
        label = "Группа · вуз" if is_vuz(user.group) else "Группа"
        # Курс зашит в номер набора (ДП-26 → 1, ГИ-23 → 3). Поле
        # ``user.course`` для колледжа заполнялось вручную вопросом
        # «на каком ты курсе?», и люди отвечали наугад: ДП-26 оказывался
        # 3 курсом. Считаем из группы — ошибиться нельзя.
        course = course_from_group(user.group)
        if course:
            ident = f"{ident} · {course} курс"
    return f"🎓 <b>Расписание ПТК</b>\n\n{label}: <b>{ident}</b>\n\nВыбери действие 👇"


async def _render_menu(repo: RequestsRepo, user: User) -> tuple[str, InlineKeyboardMarkup]:
    s = await repo.settings.get_all()
    is_editor = bool(await repo.editors.get_group_for(user.id))
    return menu_text(user), menu_kb(user, s["support_link"], is_editor)


# Преподавателей в расписании 235 (колледж) и 168 (вуз). Список кнопками
# в чате превращался в простыню на сотни строк, в которой вузовских не
# было вовсе. Вместо списка — подразделение и поиск по фамилии.
TEACHER_UNIT_KB = to_inline_kb(teacher_unit_kb())


def _unit_kb() -> InlineKeyboardMarkup:
    """Первый шаг выбора — подразделение."""
    return to_inline_kb(unit_kb())


async def _college_pick_kb(repo: RequestsRepo) -> InlineKeyboardMarkup:
    return to_inline_kb(await college_pick_kb(repo))


async def _vuz_faculty_kb(repo: RequestsRepo) -> InlineKeyboardMarkup:
    return to_inline_kb(await vuz_faculty_kb(repo))


async def _vuz_form_kb(repo: RequestsRepo, faculty: str) -> InlineKeyboardMarkup:
    return to_inline_kb(await vuz_form_kb(repo, faculty))


async def _vuz_course_kb(repo: RequestsRepo, faculty: str, form: str) -> InlineKeyboardMarkup:
    return to_inline_kb(await vuz_course_kb(repo, faculty, form))


async def _vuz_group_kb(repo: RequestsRepo, faculty: str, form: str,
                        course: int) -> InlineKeyboardMarkup:
    return to_inline_kb(await vuz_group_kb(repo, faculty, form, course))


async def _teacher_search_kb(repo: RequestsRepo, vuz: bool) -> InlineKeyboardMarkup:
    return to_inline_kb(await teacher_search_kb(repo, vuz))


async def _teacher_letter_kb(repo: RequestsRepo, vuz: bool, letter: str) -> InlineKeyboardMarkup:
    return to_inline_kb(await teacher_letter_kb(repo, vuz, letter))


async def _require_identity(cb: CallbackQuery, user: User) -> bool:
    if _has_identity(user):
        return True
    await cb.answer("Сначала выбери группу или фамилию 🎯")
    return False


async def _vuz_teacher_day(repo: RequestsRepo, user: User, date: datetime.date):
    """Пары преподавателя вуза на дату — через итоговый слой.

    Раньше читали base_lesson напрямую, и это давало две беды разом:
    замены вуза не применялись (их 160), а одна пара дублировалась по
    числу групп, где преподаватель ведёт, потому что ключ склейки в
    format_day требует точного совпадения предмета.

    Теперь идём по группам, где он ведёт пары в этот день, и берём
    get_day_slots — тот же путь, что у студента: с заменами, weeks и
    чётностью.
    """
    from tgbot.services.schedule_layer import get_day_slots
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
        return (s.para, s.para_end, re.sub(r"[\s.()]+", "", (s.subject or "")).lower(),
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
    группы из base_lesson, включая @vuz. _vuz_teacher_day читает тот же
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
            if not (str(getattr(c, "group", "") or "").endswith(VUZ_SUFFIX)
                    and (c.para, _subj_key(c)) in covered)]


async def _user_lessons(repo: RequestsRepo, user: User, date: datetime.date):
    if _is_teacher(user):
        college = await repo.college_lessons.get_for_teacher_date(user.teacher_name, date)
        vuz = await _vuz_teacher_day(repo, user, date)
        college = _drop_vuz_covered(college, vuz)
        return sorted([*college, *vuz], key=lambda l: l.para)
    return await repo.college_lessons.get_for_group_date(user.group, date)


async def _user_lessons_range(repo: RequestsRepo, user: User, start: datetime.date, end: datetime.date):
    if _is_teacher(user):
        rows = list(await repo.college_lessons.get_for_teacher_range(
            user.teacher_name, start, end))
        # Вуз в неделю не попадал вовсе: у преподавателя только с
        # вузовскими парами экран «Неделя» был пустым, хотя «Сегодня»
        # показывал шесть дней с парами.
        # Те же дубли, что и на экране дня: college_lesson для вуза и
        # _vuz_teacher_day отдают одни и те же пары.
        vuz_rows = []
        day = start
        while day <= end:
            vuz_rows.extend(await _vuz_teacher_day(repo, user, day))
            day += datetime.timedelta(days=1)
        rows = _drop_vuz_covered(rows, vuz_rows)
        return sorted([*rows, *vuz_rows], key=lambda l: (l.date, l.para))
    return await repo.college_lessons.get_for_group_range(user.group, start, end)


async def _course_group_map(repo: RequestsRepo, user: User) -> dict[str, str] | None:
    if _is_teacher(user):
        m = await repo.users.get_group_course_map()
        return m or None
    cg = bells_group(user.group, user.course)
    return {user.group: cg} if cg else None


def _fmt(user: User, date: datetime.date, lessons, bell, lunches, gcg=None) -> str:
    """Текст дня для пользователя.

    ``meta`` был перевёрнут: студент видел преподавателя, а преподаватель
    — группу. Плюс преподавателю нужно склеивать поток: физкультура у
    шести групп — это одна пара, а не шесть.
    """
    is_teacher = _is_teacher(user)
    return format_day(
        date, lessons, bell, lunches, user.bell_detail,
        meta="group" if is_teacher else "teacher",
        show_rov=not is_teacher,
        group_course_group=gcg,
        merge_groups=is_teacher,
    )


@user_router.message(CommandStart())
async def start(message: Message, user: User, repo: RequestsRepo, state: FSMContext):
    await state.clear()
    if _has_identity(user):
        # Сразу показываем сегодняшний день — это то, за чем открывают бота.
        # Меню остаётся кнопкой под сообщением.
        await message.answer(await _day_text(repo, user, datetime.date.today()),
                             reply_markup=BOTTOM_KB)
        text, kb = await _render_menu(repo, user)
        await message.answer(text, reply_markup=kb)
    else:
        await message.answer("🎓 Привет! Кто ты?", reply_markup=ROLE_KB)


@user_router.message(Command("group"))
async def set_group_cmd(message: Message, repo: RequestsRepo, user: User):
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Формат: /group ТЭ-26ФП")
        return
    group = parts[1].strip().upper()
    # `/group` — единственный текстовый ввод группы, и он писал вслепую:
    # `/group ХХХ-99` записывался, день выходил пустым, и студент решал,
    # что пар нет. Настоящая причина — опечатка.
    known = await repo.base_lessons.get_groups()
    if group not in known:
        # Частая опечатка — одна буква или префикс; подсказываем похожие.
        close = [g for g in known if group[:4] and (group[:4] in g or g[:4] in group)][:5]
        hint = "\n\nМожет быть: " + ", ".join(close) if close else ""
        await message.answer(
            f"Группы «{group}» нет в расписании.{hint}\n\n"
            f"Посмотреть список: /menu",
            reply_markup=BACK_KB)
        return
    await repo.users.set_role(user.id, "student")
    await repo.users.set_group(user.id, group)
    user.role = "student"
    user.group = group
    # Курс — из номера набора, спрашивать нечего.
    await repo.users.set_course(user.id, course_from_group(group))
    text, kb = await _render_menu(repo, user)
    await message.answer(f"Твоя группа: <b>{group}</b>\n\n{text}", reply_markup=kb)


@user_router.callback_query(F.data == "role:student")
async def cb_role_student(cb: CallbackQuery, repo: RequestsRepo, user: User):
    await repo.users.set_role(user.id, "student")
    await cb.message.edit_text("🎓 Где ты учишься?", reply_markup=_unit_kb())
    await cb.answer()


@user_router.callback_query(F.data == "role:teacher")
async def cb_role_teacher(cb: CallbackQuery, user: User):
    # Роль здесь НЕ пишется: если человек уйдёт на этом шаге, в базе
    # останется role='teacher' без фамилии, и он застрянет — /start
    # снова спросит роль, а выбрать фамилию будет негде. Роль ставит
    # cb_teacher вместе с фамилией.
    await cb.message.edit_text("👨‍🏫 Где ты преподаёшь?", reply_markup=TEACHER_UNIT_KB)
    await cb.answer()


@user_router.callback_query(F.data == "role_switch")
async def cb_role_switch(cb: CallbackQuery, repo: RequestsRepo, user: User):
    await repo.users.set_group(user.id, None)
    await repo.users.set_teacher_name(user.id, None)
    await repo.users.set_course(user.id, None)
    await cb.message.edit_text("🎓 Кто ты?", reply_markup=ROLE_KB)
    await cb.answer()


@user_router.callback_query(F.data == "pick")
async def cb_pick(cb: CallbackQuery, repo: RequestsRepo):
    await cb.message.edit_text("🎓 Где ты учишься?", reply_markup=_unit_kb())
    await cb.answer()


@user_router.callback_query(F.data == "unit:college")
async def cb_unit_college(cb: CallbackQuery, repo: RequestsRepo):
    await cb.message.edit_text("🏫 Выбери свою группу 👇",
                               reply_markup=await _college_pick_kb(repo))
    await cb.answer()


@user_router.callback_query(F.data == "unit:vuz")
async def cb_unit_vuz(cb: CallbackQuery, repo: RequestsRepo):
    kb = await _vuz_faculty_kb(repo)
    if len(kb.inline_keyboard) == 1:
        # Групп вуза ещё нет — не показываем пустой экран.
        await cb.answer("Расписание вуза пока не загружено", show_alert=True)
        return
    await cb.message.edit_text("🎓 Выбери факультет 👇", reply_markup=kb)
    await cb.answer()


@user_router.callback_query(F.data.startswith("vu:fac:"))
async def cb_vuz_faculty(cb: CallbackQuery, repo: RequestsRepo):
    faculty = cb.data.split(":")[2]
    forms = sorted({g.form for g in await repo.vuz_groups.all()
                    if g.faculty == faculty})
    # Одна форма — незачем спрашивать, сразу курсы.
    if len(forms) == 1:
        await cb.message.edit_text(
            f"{FACULTY_NAMES.get(faculty, faculty)}\n\nВыбери курс 👇",
            reply_markup=await _vuz_course_kb(repo, faculty, forms[0]))
        await cb.answer()
        return
    await cb.message.edit_text(
        f"{FACULTY_NAMES.get(faculty, faculty)}\n\nВыбери форму обучения 👇",
        reply_markup=await _vuz_form_kb(repo, faculty))
    await cb.answer()


@user_router.callback_query(F.data.startswith("vu:form:"))
async def cb_vuz_form(cb: CallbackQuery, repo: RequestsRepo):
    _, _, faculty, form = cb.data.split(":")
    await cb.message.edit_text(
        f"{FACULTY_NAMES.get(faculty, faculty)} · {FORM_NAMES.get(form, form)}\n\n"
        f"Выбери курс 👇",
        reply_markup=await _vuz_course_kb(repo, faculty, form))
    await cb.answer()


@user_router.callback_query(F.data.startswith("vu:cr:"))
async def cb_vuz_course(cb: CallbackQuery, repo: RequestsRepo):
    _, _, faculty, form, course = cb.data.split(":")
    await cb.message.edit_text(
        f"{FACULTY_NAMES.get(faculty, faculty)} · {FORM_NAMES.get(form, form)}"
        f" · {course} курс\n\nВыбери группу 👇",
        reply_markup=await _vuz_group_kb(repo, faculty, form, int(course)))
    await cb.answer()


@user_router.callback_query(F.data.startswith("vu:g:"))
async def cb_vuz_group(cb: CallbackQuery, repo: RequestsRepo, user: User):
    """Группа вуза выбрана. Курс берём из справочника, не угадываем."""
    name = cb.data[5:]
    info = await repo.vuz_groups.get(name)
    await repo.users.set_role(user.id, "student")
    await repo.users.set_group(user.id, name)
    course = info.course if info else None
    if course:
        await repo.users.set_course(user.id, course)
    user.role = "student"
    user.group = name
    user.course = course
    text, kb = await _render_menu(repo, user)
    await cb.message.edit_text(
        f"🎓 Твоя группа: <b>{strip_unit(name)}</b>"
        f"\nВуз · {FACULTY_NAMES.get(info.faculty, info.faculty) if info else ''}"
        f"\n\n{text}", reply_markup=kb)
    await cb.answer(f"{strip_unit(name)}")


@user_router.callback_query(F.data == "pick_teacher")
async def cb_pick_teacher(cb: CallbackQuery, repo: RequestsRepo):
    await cb.message.edit_text("👨‍🏫 Где ты преподаёшь?", reply_markup=TEACHER_UNIT_KB)
    await cb.answer()


@user_router.callback_query(F.data == "pick_course")
async def cb_pick_course(cb: CallbackQuery, repo: RequestsRepo, user: User):
    """Смена курса — только у вуза, и только сменой группы.

    Раньше у колледжа курс выбирался вручную кнопками 1–4. Курс и так
    зашит в номер набора (ДП-26 → 1), поэтому ручной выбор был лишним
    шагом, на котором ошибались: ДП-26 оказывался 3 курсом, и человек
    получал звонки чужого потока. Теперь курс считается из группы.
    """
    info = await repo.vuz_groups.get(user.group) if is_vuz(user.group) else None
    if info is None:
        # Колледж и «группа не выбрана»: менять нечего, курс выводится
        # из группы. Честно говорим это вместо кнопок 1–4.
        await cb.message.edit_text(
            "Курс определяется группой автоматически: ДП-26 → 1 курс.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🗓 Сменить группу",
                                      callback_data="settings:group")],
                [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu")],
            ]))
        await cb.answer()
        return

    courses = await repo.vuz_groups.courses(info.faculty, info.form)
    buttons = [InlineKeyboardButton(
        text=f"{c} курс", callback_data=f"vu:cr:{info.faculty}:{info.form}:{c}")
        for c in courses]
    rows = [buttons[i:i + 3] for i in range(0, len(buttons), 3)]
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="settings")])
    await cb.message.edit_text(
        f"Сейчас {info.course} курс. На какой перевести? 👇",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await cb.answer()


@user_router.callback_query(F.data == "settings")
async def cb_settings(cb: CallbackQuery, user: User, repo: RequestsRepo, state: FSMContext):
    await state.clear()
    await cb.message.edit_text(_settings_text(user), reply_markup=settings_kb(user))
    await cb.answer()


@user_router.callback_query(F.data.startswith("group:"))
async def cb_group(cb: CallbackQuery, repo: RequestsRepo, user: User):
    group = cb.data.split(":", 1)[1]
    await repo.users.set_role(user.id, "student")
    await repo.users.set_group(user.id, group)
    # `unit` больше не пишем: поле убрано миграцией 0010, подразделение
    # кодируется суффиксом @vuz в самом имени группы.
    user.role = "student"
    user.group = group
    await repo.users.set_course(user.id, course_from_group(group))
    text, kb = await _render_menu(repo, user)
    await cb.message.edit_text(f"Твоя группа: <b>{group}</b>\n\n{text}", reply_markup=kb)
    await cb.answer(f"Группа {group}")


@user_router.callback_query(F.data.startswith("course:"))
async def cb_course(cb: CallbackQuery, repo: RequestsRepo, user: User):
    """Кнопки старого экрана «на каком ты курсе?».

    Экран убран, но сообщения с ним остались в чатах у людей — тап по
    старой кнопке не должен висеть без ответа. Курс молча приводим к
    тому, что следует из группы.
    """
    if user.group:
        await repo.users.set_course(user.id, course_from_group(user.group))
        user.course = course_from_group(user.group)
    text, kb = await _render_menu(repo, user)
    await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer(f"{user.course or 1} курс")


@user_router.callback_query(F.data.startswith("tunit:"))
async def cb_teacher_unit(cb: CallbackQuery, repo: RequestsRepo):
    vuz = cb.data.split(":", 1)[1] == "vuz"
    where = "вуза" if vuz else "колледжа"
    await cb.message.edit_text(
        f"👨‍🏫 Преподаватели {where}\n\nВыбери первую букву фамилии 👇",
        reply_markup=await _teacher_search_kb(repo, vuz))
    await cb.answer()


@user_router.callback_query(F.data.startswith("tlet:"))
async def cb_teacher_letter(cb: CallbackQuery, repo: RequestsRepo):
    _, unit, letter = cb.data.split(":", 2)
    vuz = unit == "vuz"
    await cb.message.edit_text(
        f"👨‍🏫 Фамилии на «{letter}»\n\nВыбери себя 👇",
        reply_markup=await _teacher_letter_kb(repo, vuz, letter))
    await cb.answer()


@user_router.callback_query(F.data.startswith("teacher:"))
async def cb_teacher(cb: CallbackQuery, repo: RequestsRepo, user: User):
    name = cb.data.split(":", 1)[1]
    await repo.users.set_role(user.id, "teacher")
    await repo.users.set_teacher_name(user.id, name)
    text, kb = await _render_menu(repo, user)
    await cb.message.edit_text(f"Преподаватель: <b>{name}</b>\n\n{text}", reply_markup=kb)
    await cb.answer(name)


@user_router.callback_query(F.data == "menu")
async def cb_menu(cb: CallbackQuery, user: User, repo: RequestsRepo, state: FSMContext):
    await state.clear()
    text, kb = await _render_menu(repo, user)
    await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer()


# Что сказать человеку без группы или фамилии. Раньше он получал
# «Занятий нет 🙌» — ложь: бот не знает его группы, а не расписание пусто.
NO_IDENTITY = ("🎯 <b>Сначала выбери группу</b>\n\n"
               "Пока бот не знает, где ты учишься, расписания у него для "
               "тебя нет.")


async def _day_text(repo: RequestsRepo, user: User, date: datetime.date) -> str:
    """Текст дня. Сама логика — в ядре, здесь только сбор параметров.

    Раньше функция на 113 строк и решала, что показать, и склеивала
    HTML. Теперь это два шага в core: build_day решает, render_day
    рисует. Проверено побайтово на живой базе: 4704 случая (336
    пользователей × 14 дат), 0 расхождений со старой версией.
    """
    bell, lunches = await repo.bell_schedule.get_context()
    gcg = await course_group_map(repo, user)
    view = await build_day(repo, user, date)
    return render_day(view, bell=bell, lunches=lunches,
                      detail=user.bell_detail, is_teacher=is_teacher(user),
                      gcg=gcg)


async def _show_day(cb: CallbackQuery, repo: RequestsRepo, user: User, date: datetime.date):
    """Показать карточку дня, пережив лимит правок Telegram.

    В групповом чате несколько человек листают дни одной кнопкой, и
    Telegram отвечает 429 «Flood control exceeded on EditMessageText»
    с retry_after. Исключение доезжало до обработчика ошибок, человек
    видел «Что-то пошло не так», а админ — тревогу (02.11.2026, шесть
    таких за три часа, чат -1004366988460).

    Ждём столько, сколько просят, и повторяем один раз. Второй 429 не
    ловим: если не помогло, значит лимит общий и лучше честно сказать
    «попробуй позже», чем копить очередь повторов.
    """
    text = await _day_text(repo, user, date)
    try:
        await cb.message.edit_text(text, reply_markup=NAV_KB)
    except TelegramRetryAfter as e:
        await asyncio.sleep(min(getattr(e, "retry_after", 5), 10))
        await cb.message.edit_text(text, reply_markup=NAV_KB)
    await cb.answer()


@user_router.callback_query(F.data == "day:today")
async def cb_today(cb: CallbackQuery, repo: RequestsRepo, user: User):
    if not await _require_identity(cb, user):
        return
    await _show_day(cb, repo, user, datetime.date.today())


@user_router.callback_query(F.data == "day:tomorrow")
async def cb_tomorrow(cb: CallbackQuery, repo: RequestsRepo, user: User):
    if not await _require_identity(cb, user):
        return
    await _show_day(cb, repo, user, datetime.date.today() + datetime.timedelta(days=1))


async def _week_text(repo: RequestsRepo, user: User) -> str:
    """Неделя. Логика — в ядре, здесь только параметры рендера."""
    entries, ok = await build_week(repo, user)
    if not ok:
        return NO_IDENTITY
    bell, lunches = await repo.bell_schedule.get_context()
    gcg = await course_group_map(repo, user)
    return render_week(entries, bell=bell, lunches=lunches,
                       detail=user.bell_detail, is_teacher=is_teacher(user),
                       gcg=gcg)


@user_router.callback_query(F.data == "week")
async def cb_week(cb: CallbackQuery, repo: RequestsRepo, user: User):
    if not await _require_identity(cb, user):
        return
    await cb.message.edit_text(await _week_text(repo, user), reply_markup=NAV_KB)
    await cb.answer()


@user_router.callback_query(F.data == "bell")
async def cb_bell(cb: CallbackQuery, repo: RequestsRepo, user: User):
    """Сетка звонков — своя для каждого подразделения.

    Раньше экран всегда показывал колледж: студент и преподаватель вуза
    видели «Разговоры о важном», деление на курсы и 5 пар вместо 8.
    """
    bell, lunches = await repo.bell_schedule.get_context()
    if user.group:
        is_vuz_user = is_vuz(user.group)
    elif _is_teacher(user):
        # У преподавателя нет группы: подразделение берём из его пар.
        # Раньше читался `user.unit`, но он у всех трёх преподавателей
        # оставался «college» — сетка вуза не показывалась никогда.
        is_vuz_user = await repo.college_lessons.is_vuz_teacher(user.teacher_name)
    else:
        is_vuz_user = False
    await cb.message.edit_text(format_bell(bell, lunches, vuz=is_vuz_user),
                               reply_markup=BACK_KB)
    await cb.answer()


HIST_PAGE = 5


async def _snapshot_lessons(repo: RequestsRepo, group: str, date: datetime.date):
    """День из архива в виде объектов, которые понимает format_day.

    `group` подставляем обязательно: в payload его нет, а без него
    format_day берёт звонки по fallback I_IV — у 2–3 курса вторая пара
    кончается в 12:20, а не в 12:40, и студент увидел бы не то время.
    """
    rows = await repo.snapshots.get(date, group)
    if not rows:
        return []
    out = []
    for d in rows:
        item = SimpleNamespace(**d)
        item.group = group
        item.time_note = getattr(item, "time_note", "") or ""
        item.para_end = getattr(item, "para_end", None) or item.para
        out.append(item)
    return out


async def _teacher_snapshot_lessons(repo: RequestsRepo, user: User,
                                    date: datetime.date):
    """Пары преподавателя за день из архива групп.

    Архив пишется по группам, поэтому перебираем группы этой даты и
    оставляем только пары нашей фамилии.
    """
    surname = (user.teacher_name or "").split()[0] if user.teacher_name else ""
    if not surname:
        return []
    out = []
    for group in await repo.snapshots.get_groups(date):
        for item in await _snapshot_lessons(repo, group, date):
            if surname in (getattr(item, "teacher", "") or ""):
                out.append(item)
    return sorted(out, key=lambda l: (l.para, l.group))


async def _hist_page(repo: RequestsRepo, user: User, before: datetime.date | None) -> tuple[str, InlineKeyboardMarkup]:
    """Окно из пяти дат, начиная с самой свежей раньше ``before``.

    Курсор лежит в callback_data, а не в FSM: переживает рестарт и не
    путается, если человек листает с двух устройств.
    """
    if _is_teacher(user):
        dates = await repo.college_lessons.get_dates_for_teacher(user.teacher_name)
        # college_lesson хранит только будущее: прошедшие дни удаляются
        # ежедневно. Без архива история преподавателя пуста у всех —
        # проверено на проде, 0 прошедших дат у всех трёх.
        for d in await repo.snapshots.get_dates_for_teacher(
                (user.teacher_name or "").split()[0] if user.teacher_name else ""):
            if d not in dates:
                dates.append(d)
    else:
        dates = await repo.college_lessons.get_dates_for_group(user.group)
        # day_snapshot — архив, который пишется каждый час. Он покрывает
        # дни, которых в college_lesson уже нет: материализация идёт на
        # 14 дней вперёд, а назад заполняется только по мере прошествия,
        # и простой бота оставляет дыру навсегда. На проде 20–22.10 были
        # в архиве и не видны в истории.
        dates = set(dates) | set(await repo.snapshots.get_dates_for_group(user.group))
    past = sorted((d for d in dates if d < datetime.date.today()), reverse=True)
    if before:
        past = [d for d in past if d < before]

    if not past:
        # У вуза история короче: college_lesson материализуется вперёд на
        # 14 дней, а назад заполняется только по мере прошествия. Поэтому
        # «Больше расписания нет» на первом заходе — норма, а не ошибка.
        # Говорим это прямо, иначе выглядит как поломка.
        text = ("📜 <b>История расписания</b>\n\n"
                "Прошедших дней пока нет — они копятся по мере учёбы.")
        return text, InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="⬅️ В меню", callback_data="menu")]])

    window = past[:HIST_PAGE]
    buttons = [InlineKeyboardButton(text=f"{d.day:02d}.{d.month:02d}",
                                    callback_data=f"hist:{d.isoformat()}")
               for d in window]
    rows = [buttons[i:i + 3] for i in range(0, len(buttons), 3)]
    if len(past) > HIST_PAGE:
        rows.append([InlineKeyboardButton(
            text="⬅️ Раньше", callback_data=f"histpage:{window[-1].isoformat()}")])
    rows.append([InlineKeyboardButton(text="⬅️ В меню", callback_data="menu")])
    return "📜 История расписания\n\nВыбери дату 👇", InlineKeyboardMarkup(inline_keyboard=rows)


@user_router.callback_query(F.data == "hist")
async def cb_hist(cb: CallbackQuery, repo: RequestsRepo, user: User):
    if not await _require_identity(cb, user):
        return
    text, kb = await _hist_page(repo, user, None)
    await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer()


@user_router.callback_query(F.data.startswith("histpage:"))
async def cb_hist_page(cb: CallbackQuery, repo: RequestsRepo, user: User):
    if not await _require_identity(cb, user):
        return
    before = datetime.date.fromisoformat(cb.data.split(":", 1)[1])
    text, kb = await _hist_page(repo, user, before)
    await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer()


@user_router.callback_query(F.data.startswith("hist:"))
async def cb_hist_date(cb: CallbackQuery, repo: RequestsRepo, user: User):
    if not await _require_identity(cb, user):
        return
    date = datetime.date.fromisoformat(cb.data.split(":", 1)[1])
    bell, lunches = await repo.bell_schedule.get_context()
    gcg = await _course_group_map(repo, user)
    lessons = await _user_lessons(repo, user, date)
    if not lessons and not _is_teacher(user) and user.group:
        lessons = await _snapshot_lessons(repo, user.group, date)
    if not lessons and _is_teacher(user):
        lessons = await _teacher_snapshot_lessons(repo, user, date)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ К истории", callback_data="hist")],
        [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu")],
    ])
    await cb.message.edit_text(_fmt(user, date, lessons, bell, lunches, gcg), reply_markup=kb)
    await cb.answer()


@user_router.callback_query(F.data == "sub:toggle")
async def cb_sub(cb: CallbackQuery, repo: RequestsRepo, user: User):
    if not await _require_identity(cb, user):
        return
    new = not user.subscribed
    await repo.users.set_subscribed(user.id, new)
    text, kb = await _render_menu(repo, user)
    await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer("Подписка включена 🔔" if new else "Подписка отключена 🔕")


@user_router.callback_query(F.data == "bell_mode")
async def cb_bell_mode(cb: CallbackQuery, repo: RequestsRepo, user: User):
    if not await _require_identity(cb, user):
        return
    cur = user.bell_mode if user.bell_mode in BELL_ORDER else BELL_ORDER[0]
    nxt = BELL_ORDER[(BELL_ORDER.index(cur) + 1) % len(BELL_ORDER)]
    await repo.users.set_bell_mode(user.id, nxt)
    user.bell_mode = nxt
    await cb.message.edit_text(_settings_text(user), reply_markup=settings_kb(user))
    await cb.answer(f"Звонки: {BELL_LABELS[nxt]}")


@user_router.callback_query(F.data == "image_toggle")
async def cb_image_toggle(cb: CallbackQuery, repo: RequestsRepo, user: User):
    new = not user.send_image
    await repo.users.set_send_image(user.id, new)
    user.send_image = new
    await cb.message.edit_text(_settings_text(user), reply_markup=settings_kb(user))
    await cb.answer("Картинки включены 🐱" if new else "Картинки отключены")


@user_router.callback_query(F.data == "detail")
async def cb_detail(cb: CallbackQuery, repo: RequestsRepo, user: User):
    cur = user.bell_detail if user.bell_detail in DETAIL_ORDER else DETAIL_ORDER[0]
    nxt = DETAIL_ORDER[(DETAIL_ORDER.index(cur) + 1) % len(DETAIL_ORDER)]
    await repo.users.set_bell_detail(user.id, nxt)
    user.bell_detail = nxt
    await cb.message.edit_text(_settings_text(user), reply_markup=settings_kb(user))
    await cb.answer(f"Детализация: {DETAIL_LABELS[nxt]}")


@user_router.callback_query(F.data == "find")
async def cb_find(cb: CallbackQuery, user: User, state: FSMContext):
    if not await _require_identity(cb, user):
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Отмена", callback_data="find:cancel")],
    ])
    await cb.message.edit_text("🔎 Напиши название предмета (например, «химия»):", reply_markup=kb)
    await state.set_state(SubjectSearch.waiting)
    await cb.answer()


@user_router.callback_query(F.data == "find:cancel")
async def cb_find_cancel(cb: CallbackQuery, user: User, repo: RequestsRepo, state: FSMContext):
    await state.clear()
    text, kb = await _render_menu(repo, user)
    await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer()


def _subject_pick(lessons: list, subj: str, limit: int = 5) -> list:
    """Подходящие пары, самые поздние первыми.

    Срез [:5] стоял ДО сортировки, а порядок задаёт репозиторий:
    get_all_for_group отдаёт date.desc(), get_all_for_teacher — date.
    Преподаватель под заголовком «последние занятия» получал самые
    старые. Сортируем сами, потом режем.
    """
    matched = [l for l in lessons if subj.casefold() in (l.subject or "").casefold()]
    matched.sort(key=lambda l: (l.date, l.para), reverse=True)
    return matched[:limit]


@user_router.message(SubjectSearch.waiting)
async def subject_answer(message: Message, repo: RequestsRepo, user: User, state: FSMContext):
    await state.clear()
    subj = message.text.strip()
    if _is_teacher(user):
        lessons = await repo.college_lessons.get_all_for_teacher(user.teacher_name)
    else:
        lessons = await repo.college_lessons.get_all_for_group(user.group)
    matched = _subject_pick(lessons, subj)
    if not matched:
        await message.answer(f"По «{subj}» ничего не нашлось", reply_markup=BACK_KB)
        return
    results = matched[:5]
    bell, lunches = await repo.bell_schedule.get_context()
    gcg = await _course_group_map(repo, user)
    by_date: dict[datetime.date, list] = {}
    for l in results:
        by_date.setdefault(l.date, []).append(l)
    parts = [_fmt(user, d, by_date[d], bell, lunches, gcg) for d in sorted(by_date, reverse=True)]
    await message.answer(f"🔎 «{subj}» — последние занятия:\n\n" + "\n\n".join(parts), reply_markup=BACK_KB)


@user_router.callback_query(F.data == "find_teacher")
async def cb_find_teacher(cb: CallbackQuery, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Отмена", callback_data="find:cancel")],
    ])
    await cb.message.edit_text("👨‍🏫 Напиши фамилию преподавателя:", reply_markup=kb)
    await state.set_state(TeacherSearch.waiting)
    await cb.answer()


@user_router.message(TeacherSearch.waiting)
async def teacher_answer(message: Message, repo: RequestsRepo, user: User, state: FSMContext):
    await state.clear()
    q = message.text.strip()
    lessons = await repo.college_lessons.get_all_lessons()
    matched = [l for l in lessons if q.casefold() in (l.teacher or "").casefold()]
    if not matched:
        await message.answer(f"Преподаватель «{q}» не найден", reply_markup=BACK_KB)
        return
    today = datetime.date.today()
    week_end = today + datetime.timedelta(days=6)
    upcoming = [l for l in matched if today <= l.date <= week_end]
    scope = upcoming if upcoming else matched[-12:]
    bell, lunches = await repo.bell_schedule.get_context()
    by_date: dict[datetime.date, list] = {}
    for l in scope:
        by_date.setdefault(l.date, []).append(l)
    if upcoming:
        # Ищем вперёд — показываем неделю целиком, как в «Неделе»:
        # пустой день у преподавателя тоже ответ, а не пропуск.
        entries = [(today + datetime.timedelta(days=i),
                    by_date.get(today + datetime.timedelta(days=i), []))
                   for i in range(7)]
    else:
        # Показываем прошедшее — пустые дни не нужны, это не расписание
        # недели, а найденные пары.
        entries = [(d, by_date[d]) for d in sorted(by_date)]
    await message.answer(
        f"👨‍🏫 «{q}»:\n\n"
        + format_teacher_results(entries, bell, lunches, user.bell_detail,
                                 merge_groups=_is_teacher(user)),
        reply_markup=BACK_KB,
    )


# Нижнее меню: три кнопки, которые нужны каждый день. Reply-клавиатура
# всегда на экране, целиться в инлайн-кнопку под сообщением не надо.
# Обработчики стоят ДО any_text — иначе он их перехватит.
BOTTOM_KB = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="📅 Сегодня"),
               KeyboardButton(text="📅 Завтра"),
               KeyboardButton(text="🗓 7 дней")]],
    resize_keyboard=True,
    is_persistent=True,
)


@user_router.message(F.text == "📅 Сегодня")
async def btn_today(message: Message, repo: RequestsRepo, user: User):
    if not _has_identity(user):
        await message.answer("Сначала выбери группу или фамилию 🎯", reply_markup=ROLE_KB)
        return
    await message.answer(await _day_text(repo, user, datetime.date.today()),
                         reply_markup=NAV_KB)


@user_router.message(F.text == "📅 Завтра")
async def btn_tomorrow(message: Message, repo: RequestsRepo, user: User):
    if not _has_identity(user):
        await message.answer("Сначала выбери группу или фамилию 🎯", reply_markup=ROLE_KB)
        return
    await message.answer(
        await _day_text(repo, user, datetime.date.today() + datetime.timedelta(days=1)),
        reply_markup=NAV_KB)


@user_router.message(F.text.in_({"🗓 7 дней", "🗓 Неделя"}))
async def btn_week(message: Message, repo: RequestsRepo, user: User):
    if not _has_identity(user):
        await message.answer("Сначала выбери группу или фамилию 🎯", reply_markup=ROLE_KB)
        return
    await message.answer(await _week_text(repo, user), reply_markup=NAV_KB)


@user_router.message(F.text, ~F.text.startswith("/"))
async def any_text(message: Message, repo: RequestsRepo, user: User):
    """Не молчим на непонятный текст — показываем меню и нижние кнопки."""
    text, kb = await _render_menu(repo, user)
    await message.answer(text, reply_markup=kb)
    await message.answer("Кнопки внизу — быстрый доступ 👇", reply_markup=BOTTOM_KB)
