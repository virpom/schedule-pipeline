import datetime

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from common.schedule import (
    BELL_LABELS,
    BELL_ORDER,
    DETAIL_LABELS,
    DETAIL_ORDER,
    course_group_from_course,
    format_bell,
    format_day,
    format_no_lessons,
    format_not_published,
    format_site_down,
    format_teacher_results,
    format_week,
)
from infrastructure.database.models import User
from infrastructure.database.repo.requests import RequestsRepo

user_router = Router()

BACK_KB = InlineKeyboardMarkup(
    inline_keyboard=[[InlineKeyboardButton(text="⬅️ В меню", callback_data="menu")]]
)

ROLE_KB = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="🎓 Студент", callback_data="role:student")],
    [InlineKeyboardButton(text="👨‍🏫 Преподаватель", callback_data="role:teacher")],
])

COURSE_KB = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="1 курс", callback_data="course:1"),
     InlineKeyboardButton(text="2 курс", callback_data="course:2")],
    [InlineKeyboardButton(text="3 курс", callback_data="course:3"),
     InlineKeyboardButton(text="4 курс", callback_data="course:4")],
    [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu")],
])


class SubjectSearch(StatesGroup):
    waiting = State()


class TeacherSearch(StatesGroup):
    waiting = State()


class GroupSearch(StatesGroup):
    waiting = State()


def _is_teacher(user: User) -> bool:
    return user.role == "teacher"


def _has_identity(user: User) -> bool:
    return bool(user.teacher_name) if _is_teacher(user) else bool(user.group)


def _on_off(value: bool) -> str:
    return "вкл" if value else "выкл"


def menu_kb(user: User, support_link: str = "") -> InlineKeyboardMarkup:
    sub_text = "🔕 Отписаться" if user.subscribed else "🔔 Подписаться"
    detail_label = DETAIL_LABELS.get(user.bell_detail, "кратко")
    bell_label = BELL_LABELS.get(user.bell_mode, "выкл")

    second_search = "👥 Группа" if _is_teacher(user) else "👨‍🏫 Преподаватель"
    second_search_cb = "find_group" if _is_teacher(user) else "find_teacher"

    rows = [
        [InlineKeyboardButton(text="📅 Сегодня", callback_data="day:today"),
         InlineKeyboardButton(text="📅 Завтра", callback_data="day:tomorrow")],
        [InlineKeyboardButton(text="🗓 Вся неделя", callback_data="week"),
         InlineKeyboardButton(text="📜 История", callback_data="hist")],
        [InlineKeyboardButton(text="⏰ Расписание звонков", callback_data="bell"),
         InlineKeyboardButton(text=f"🕒 Детализация: {detail_label}", callback_data="detail")],
        [InlineKeyboardButton(text="🔎 Предмет", callback_data="find"),
         InlineKeyboardButton(text=second_search, callback_data=second_search_cb)],
        [InlineKeyboardButton(text=sub_text, callback_data="sub:toggle")],
        [InlineKeyboardButton(text=f"🔔 Звонки: {bell_label}", callback_data="bell_mode")],
        [InlineKeyboardButton(text="⚙️ Настройки", callback_data="settings")],
    ]
    if support_link:
        rows.append([InlineKeyboardButton(text="📨 Поддержка", url=support_link)])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def settings_kb(user: User) -> InlineKeyboardMarkup:
    rows = []
    if _is_teacher(user):
        rows.append([InlineKeyboardButton(text="🎯 Сменить фамилию", callback_data="pick_teacher")])
    else:
        rows.append([InlineKeyboardButton(text="🎯 Сменить группу", callback_data="pick")])
        rows.append([InlineKeyboardButton(text="🎯 Сменить курс", callback_data="pick_course")])
        rows.append([InlineKeyboardButton(text=f"🐱 Картинки: {_on_off(user.send_image)}", callback_data="image_toggle")])
    rows.append([InlineKeyboardButton(text="🎭 Сменить роль", callback_data="role_switch")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def menu_text(user: User) -> str:
    if _is_teacher(user):
        label, ident = "Преподаватель", user.teacher_name or "не выбрана"
    else:
        label = "Группа"
        ident = user.group or "не выбрана"
        if user.course:
            ident = f"{ident} · {user.course} курс"
    return f"🎓 <b>Расписание ПТК</b>\n\n{label}: <b>{ident}</b>\n\nВыбери действие 👇"


async def _render_menu(repo: RequestsRepo, user: User) -> tuple[str, InlineKeyboardMarkup]:
    s = await repo.settings.get_all()
    return menu_text(user), menu_kb(user, s["support_link"])


async def _pick_kb(repo: RequestsRepo) -> InlineKeyboardMarkup:
    groups = await repo.college_lessons.get_groups()
    buttons = [InlineKeyboardButton(text=g, callback_data=f"group:{g}") for g in groups]
    rows = [buttons[i:i + 4] for i in range(0, len(buttons), 4)]
    rows.append([InlineKeyboardButton(text="⬅️ В меню", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _teacher_pick_kb(repo: RequestsRepo) -> InlineKeyboardMarkup:
    teachers = await repo.college_lessons.get_teachers()
    buttons = [InlineKeyboardButton(text=t, callback_data=f"teacher:{t}") for t in teachers]
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    rows.append([InlineKeyboardButton(text="⬅️ В меню", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _require_identity(cb: CallbackQuery, user: User) -> bool:
    if _has_identity(user):
        return True
    await cb.answer("Сначала выбери группу или фамилию 🎯")
    return False


async def _user_lessons(repo: RequestsRepo, user: User, date: datetime.date):
    if _is_teacher(user):
        return await repo.college_lessons.get_for_teacher_date(user.teacher_name, date)
    return await repo.college_lessons.get_for_group_date(user.group, date)


async def _user_lessons_range(repo: RequestsRepo, user: User, start: datetime.date, end: datetime.date):
    if _is_teacher(user):
        return await repo.college_lessons.get_for_teacher_range(user.teacher_name, start, end)
    return await repo.college_lessons.get_for_group_range(user.group, start, end)


async def _course_group_map(repo: RequestsRepo, user: User) -> dict[str, str] | None:
    if _is_teacher(user):
        m = await repo.users.get_group_course_map()
        return m or None
    cg = course_group_from_course(user.course)
    return {user.group: cg} if cg else None


def _fmt(user: User, date: datetime.date, lessons, bell, lunches, gcg=None) -> str:
    return format_day(
        date, lessons, bell, lunches, user.bell_detail,
        meta="group" if _is_teacher(user) else "teacher",
        show_rov=not _is_teacher(user),
        group_course_group=gcg,
    )


@user_router.message(CommandStart())
async def start(message: Message, user: User, repo: RequestsRepo, state: FSMContext):
    await state.clear()
    if _has_identity(user):
        if not _is_teacher(user) and not user.course:
            await message.answer(
                f"🎓 Твоя группа: <b>{user.group}</b>\n\nНа каком ты курсе? 👇",
                reply_markup=COURSE_KB,
            )
        else:
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
    await repo.users.set_role(user.id, "student")
    await repo.users.set_group(user.id, group)
    user.role = "student"
    user.group = group
    if user.course:
        text, kb = await _render_menu(repo, user)
        await message.answer(f"Твоя группа: <b>{group}</b>\n\n{text}", reply_markup=kb)
    else:
        await message.answer(f"Твоя группа: <b>{group}</b>\n\nНа каком ты курсе? 👇", reply_markup=COURSE_KB)


@user_router.callback_query(F.data == "role:student")
async def cb_role_student(cb: CallbackQuery, repo: RequestsRepo, user: User):
    await repo.users.set_role(user.id, "student")
    await cb.message.edit_text("🎓 Выбери свою группу 👇", reply_markup=await _pick_kb(repo))
    await cb.answer()


@user_router.callback_query(F.data == "role:teacher")
async def cb_role_teacher(cb: CallbackQuery, repo: RequestsRepo, user: User):
    await repo.users.set_role(user.id, "teacher")
    await cb.message.edit_text("👨‍🏫 Выбери себя из списка 👇", reply_markup=await _teacher_pick_kb(repo))
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
    await cb.message.edit_text("Выбери свою группу 👇", reply_markup=await _pick_kb(repo))
    await cb.answer()


@user_router.callback_query(F.data == "pick_teacher")
async def cb_pick_teacher(cb: CallbackQuery, repo: RequestsRepo):
    await cb.message.edit_text("👨‍🏫 Выбери себя из списка 👇", reply_markup=await _teacher_pick_kb(repo))
    await cb.answer()


@user_router.callback_query(F.data == "pick_course")
async def cb_pick_course(cb: CallbackQuery):
    await cb.message.edit_text("На каком ты курсе? 👇", reply_markup=COURSE_KB)
    await cb.answer()


@user_router.callback_query(F.data == "settings")
async def cb_settings(cb: CallbackQuery, user: User, repo: RequestsRepo, state: FSMContext):
    await state.clear()
    await cb.message.edit_text("⚙️ <b>Настройки</b>\n\nВыбери действие 👇", reply_markup=settings_kb(user))
    await cb.answer()


@user_router.callback_query(F.data.startswith("group:"))
async def cb_group(cb: CallbackQuery, repo: RequestsRepo, user: User):
    group = cb.data.split(":", 1)[1]
    await repo.users.set_role(user.id, "student")
    await repo.users.set_group(user.id, group)
    user.role = "student"
    user.group = group
    if user.course:
        text, kb = await _render_menu(repo, user)
        await cb.message.edit_text(f"Твоя группа: <b>{group}</b>\n\n{text}", reply_markup=kb)
    else:
        await cb.message.edit_text(f"Твоя группа: <b>{group}</b>\n\nНа каком ты курсе? 👇", reply_markup=COURSE_KB)
    await cb.answer(f"Группа {group}")


@user_router.callback_query(F.data.startswith("course:"))
async def cb_course(cb: CallbackQuery, repo: RequestsRepo, user: User):
    course = int(cb.data.split(":", 1)[1])
    await repo.users.set_course(user.id, course)
    user.course = course
    text, kb = await _render_menu(repo, user)
    await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer(f"{course} курс")


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


async def _show_day(cb: CallbackQuery, repo: RequestsRepo, user: User, date: datetime.date):
    bell, lunches = await repo.bell_schedule.get_context()
    gcg = await _course_group_map(repo, user)
    lessons = await _user_lessons(repo, user, date)
    if lessons:
        text = _fmt(user, date, lessons, bell, lunches, gcg)
    else:
        note = None
        if not _is_teacher(user):
            note = await repo.no_lessons.get_note(date, user.group)
        published = await repo.schedule_files.get_hash(date) is not None
        if note or published:
            text = format_no_lessons(date, note)
        else:
            s = await repo.settings.get_all()
            if s.get("site_down") == "1":
                text = format_site_down(date)
            else:
                deadline = int(s.get("deadline_hour", 20) or 20)
                now = datetime.datetime.now()
                if 0 <= deadline <= 23 and now.hour >= deadline:
                    text = format_no_lessons(date)
                else:
                    text = format_not_published(date)
        for i in range(1, 8):
            d = date + datetime.timedelta(days=i)
            nxt = await _user_lessons(repo, user, d)
            if nxt:
                text += "\n\nБлижайшее —\n" + _fmt(user, d, nxt, bell, lunches, gcg)
                break
    await cb.message.edit_text(text, reply_markup=BACK_KB)
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


@user_router.callback_query(F.data == "week")
async def cb_week(cb: CallbackQuery, repo: RequestsRepo, user: User):
    if not await _require_identity(cb, user):
        return
    bell, lunches = await repo.bell_schedule.get_context()
    gcg = await _course_group_map(repo, user)
    start = datetime.date.today()
    end = start + datetime.timedelta(days=6)
    lessons = await _user_lessons_range(repo, user, start, end)
    by_date: dict[datetime.date, list] = {}
    for l in lessons:
        by_date.setdefault(l.date, []).append(l)
    entries = [(d, by_date[d]) for d in sorted(by_date)]
    meta = "group" if _is_teacher(user) else "teacher"
    show_rov = not _is_teacher(user)
    await cb.message.edit_text(
        format_week(entries, bell, lunches, user.bell_detail, meta, show_rov, gcg),
        reply_markup=BACK_KB,
    )
    await cb.answer()


@user_router.callback_query(F.data == "bell")
async def cb_bell(cb: CallbackQuery, repo: RequestsRepo):
    bell, lunches = await repo.bell_schedule.get_context()
    await cb.message.edit_text(format_bell(bell, lunches), reply_markup=BACK_KB)
    await cb.answer()


@user_router.callback_query(F.data == "hist")
async def cb_hist(cb: CallbackQuery, repo: RequestsRepo, user: User):
    if not await _require_identity(cb, user):
        return
    if _is_teacher(user):
        dates = await repo.college_lessons.get_dates_for_teacher(user.teacher_name)
    else:
        dates = await repo.college_lessons.get_dates_for_group(user.group)
    past = [d for d in dates if d < datetime.date.today()]
    if not past:
        await cb.message.edit_text("📜 Истории расписания пока нет", reply_markup=BACK_KB)
        await cb.answer()
        return
    buttons = [
        InlineKeyboardButton(text=f"{d.day:02d}.{d.month:02d}", callback_data=f"hist:{d.isoformat()}")
        for d in past[:28]
    ]
    rows = [buttons[i:i + 4] for i in range(0, len(buttons), 4)]
    rows.append([InlineKeyboardButton(text="⬅️ В меню", callback_data="menu")])
    await cb.message.edit_text(
        "📜 История расписания\n\nВыбери дату 👇",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await cb.answer()


@user_router.callback_query(F.data.startswith("hist:"))
async def cb_hist_date(cb: CallbackQuery, repo: RequestsRepo, user: User):
    if not await _require_identity(cb, user):
        return
    date = datetime.date.fromisoformat(cb.data.split(":", 1)[1])
    bell, lunches = await repo.bell_schedule.get_context()
    gcg = await _course_group_map(repo, user)
    lessons = await _user_lessons(repo, user, date)
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
    text, kb = await _render_menu(repo, user)
    await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer(f"Звонки: {BELL_LABELS[nxt]}")


@user_router.callback_query(F.data == "image_toggle")
async def cb_image_toggle(cb: CallbackQuery, repo: RequestsRepo, user: User):
    new = not user.send_image
    await repo.users.set_send_image(user.id, new)
    user.send_image = new
    await cb.message.edit_text("⚙️ <b>Настройки</b>\n\nВыбери действие 👇", reply_markup=settings_kb(user))
    await cb.answer("Картинки включены 🐱" if new else "Картинки отключены")


@user_router.callback_query(F.data == "detail")
async def cb_detail(cb: CallbackQuery, repo: RequestsRepo, user: User):
    cur = user.bell_detail if user.bell_detail in DETAIL_ORDER else DETAIL_ORDER[0]
    nxt = DETAIL_ORDER[(DETAIL_ORDER.index(cur) + 1) % len(DETAIL_ORDER)]
    await repo.users.set_bell_detail(user.id, nxt)
    text, kb = await _render_menu(repo, user)
    await cb.message.edit_text(text, reply_markup=kb)
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


@user_router.message(SubjectSearch.waiting)
async def subject_answer(message: Message, repo: RequestsRepo, user: User, state: FSMContext):
    await state.clear()
    subj = message.text.strip()
    if _is_teacher(user):
        lessons = await repo.college_lessons.get_all_for_teacher(user.teacher_name)
    else:
        lessons = await repo.college_lessons.get_all_for_group(user.group)
    matched = [l for l in lessons if subj.casefold() in l.subject.casefold()]
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
async def teacher_answer(message: Message, repo: RequestsRepo, state: FSMContext):
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
    entries = [(d, by_date[d]) for d in sorted(by_date)]
    await message.answer(
        f"👨‍🏫 «{q}»:\n\n" + format_teacher_results(entries, bell, lunches),
        reply_markup=BACK_KB,
    )


@user_router.callback_query(F.data == "find_group")
async def cb_find_group(cb: CallbackQuery, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Отмена", callback_data="find:cancel")],
    ])
    await cb.message.edit_text("👥 Напиши номер группы (например, ДП-26):", reply_markup=kb)
    await state.set_state(GroupSearch.waiting)
    await cb.answer()


@user_router.message(GroupSearch.waiting)
async def group_answer(message: Message, repo: RequestsRepo, state: FSMContext):
    await state.clear()
    group = message.text.strip().upper()
    bell, lunches = await repo.bell_schedule.get_context()
    start = datetime.date.today()
    end = start + datetime.timedelta(days=6)
    lessons = await repo.college_lessons.get_for_group_range(group, start, end)
    if not lessons:
        await message.answer(f"У группы «{group}» пар на неделю нет", reply_markup=BACK_KB)
        return
    by_date: dict[datetime.date, list] = {}
    for l in lessons:
        by_date.setdefault(l.date, []).append(l)
    entries = [(d, by_date[d]) for d in sorted(by_date)]
    await message.answer(
        f"👥 «{group}» — неделя:\n\n" + format_teacher_results(entries, bell, lunches),
        reply_markup=BACK_KB,
    )


@user_router.message(F.text, ~F.text.startswith("/"))
async def any_text(message: Message, repo: RequestsRepo, user: User):
    text, kb = await _render_menu(repo, user)
    await message.answer(text, reply_markup=kb)
