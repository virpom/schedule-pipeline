import datetime

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from common.schedule import (
    DETAIL_LABELS,
    DETAIL_ORDER,
    format_bell,
    format_day,
    format_teacher_results,
    format_week,
)
from infrastructure.database.models import User
from infrastructure.database.repo.requests import RequestsRepo

user_router = Router()

BACK_KB = InlineKeyboardMarkup(
    inline_keyboard=[[InlineKeyboardButton(text="⬅️ В меню", callback_data="menu")]]
)


class SubjectSearch(StatesGroup):
    waiting = State()


class TeacherSearch(StatesGroup):
    waiting = State()


def menu_kb(subscribed: bool, bell_detail: str = "brief") -> InlineKeyboardMarkup:
    sub_text = "🔕 Отписаться" if subscribed else "🔔 Подписаться"
    detail_label = DETAIL_LABELS.get(bell_detail, "кратко")
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Сегодня", callback_data="day:today"),
         InlineKeyboardButton(text="📅 Завтра", callback_data="day:tomorrow")],
        [InlineKeyboardButton(text="🗓 Вся неделя", callback_data="week"),
         InlineKeyboardButton(text="📜 История", callback_data="hist")],
        [InlineKeyboardButton(text="⏰ Звонки", callback_data="bell"),
         InlineKeyboardButton(text=f"🕒 Детализация: {detail_label}", callback_data="detail")],
        [InlineKeyboardButton(text="🔎 Предмет", callback_data="find"),
         InlineKeyboardButton(text="👨‍🏫 Преподаватель", callback_data="find_teacher")],
        [InlineKeyboardButton(text=sub_text, callback_data="sub:toggle"),
         InlineKeyboardButton(text="🎯 Сменить группу", callback_data="pick")],
    ])


def menu_text(user: User) -> str:
    group = user.group or "не выбрана"
    return f"🎓 <b>Расписание ПТК</b>\n\nТвоя группа: <b>{group}</b>\n\nВыбери действие 👇"


async def _pick_kb(repo: RequestsRepo) -> InlineKeyboardMarkup:
    groups = await repo.college_lessons.get_groups()
    buttons = [InlineKeyboardButton(text=g, callback_data=f"group:{g}") for g in groups]
    rows = [buttons[i:i + 4] for i in range(0, len(buttons), 4)]
    rows.append([InlineKeyboardButton(text="⬅️ В меню", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _require_group(cb: CallbackQuery, user: User) -> bool:
    if user.group:
        return True
    await cb.answer("Сначала выбери группу 🎯")
    return False


@user_router.message(CommandStart())
async def start(message: Message, user: User, repo: RequestsRepo, state: FSMContext):
    await state.clear()
    if user.group:
        await message.answer(menu_text(user), reply_markup=menu_kb(user.subscribed, user.bell_detail))
    else:
        await message.answer(
            "🎓 Привет! Я бот расписания Политехнического колледжа ЗГУ.\n\nВыбери свою группу 👇",
            reply_markup=await _pick_kb(repo),
        )


@user_router.message(Command("group"))
async def set_group_cmd(message: Message, repo: RequestsRepo, user: User):
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Формат: /group ТЭ-26ФП")
        return
    group = parts[1].strip().upper()
    await repo.users.set_group(user.id, group)
    await message.answer(f"Твоя группа: <b>{group}</b>", reply_markup=menu_kb(user.subscribed, user.bell_detail))


@user_router.callback_query(F.data == "pick")
async def cb_pick(cb: CallbackQuery, repo: RequestsRepo):
    await cb.message.edit_text("Выбери свою группу 👇", reply_markup=await _pick_kb(repo))
    await cb.answer()


@user_router.callback_query(F.data.startswith("group:"))
async def cb_group(cb: CallbackQuery, repo: RequestsRepo, user: User):
    group = cb.data.split(":", 1)[1]
    await repo.users.set_group(user.id, group)
    await cb.message.edit_text(f"Твоя группа: <b>{group}</b>", reply_markup=menu_kb(user.subscribed, user.bell_detail))
    await cb.answer(f"Группа {group}")


@user_router.callback_query(F.data == "menu")
async def cb_menu(cb: CallbackQuery, user: User, state: FSMContext):
    await state.clear()
    await cb.message.edit_text(menu_text(user), reply_markup=menu_kb(user.subscribed, user.bell_detail))
    await cb.answer()


async def _show_day(cb: CallbackQuery, repo: RequestsRepo, user: User, date: datetime.date):
    bell, lunches = await repo.bell_schedule.get_context()
    lessons = await repo.college_lessons.get_for_group_date(user.group, date)
    if lessons:
        text = format_day(date, lessons, bell, lunches, user.bell_detail)
    else:
        text = format_day(date, [], bell, lunches, user.bell_detail)
        for i in range(1, 8):
            d = date + datetime.timedelta(days=i)
            nxt = await repo.college_lessons.get_for_group_date(user.group, d)
            if nxt:
                text += "\n\nБлижайшее —\n" + format_day(d, nxt, bell, lunches, user.bell_detail)
                break
    await cb.message.edit_text(text, reply_markup=BACK_KB)
    await cb.answer()


@user_router.callback_query(F.data == "day:today")
async def cb_today(cb: CallbackQuery, repo: RequestsRepo, user: User):
    if not await _require_group(cb, user):
        return
    await _show_day(cb, repo, user, datetime.date.today())


@user_router.callback_query(F.data == "day:tomorrow")
async def cb_tomorrow(cb: CallbackQuery, repo: RequestsRepo, user: User):
    if not await _require_group(cb, user):
        return
    await _show_day(cb, repo, user, datetime.date.today() + datetime.timedelta(days=1))


@user_router.callback_query(F.data == "week")
async def cb_week(cb: CallbackQuery, repo: RequestsRepo, user: User):
    if not await _require_group(cb, user):
        return
    bell, lunches = await repo.bell_schedule.get_context()
    start = datetime.date.today()
    end = start + datetime.timedelta(days=6)
    lessons = await repo.college_lessons.get_for_group_range(user.group, start, end)
    by_date: dict[datetime.date, list] = {}
    for l in lessons:
        by_date.setdefault(l.date, []).append(l)
    entries = [(d, by_date[d]) for d in sorted(by_date)]
    await cb.message.edit_text(format_week(entries, bell, lunches, user.bell_detail), reply_markup=BACK_KB)
    await cb.answer()


@user_router.callback_query(F.data == "bell")
async def cb_bell(cb: CallbackQuery, repo: RequestsRepo):
    bell, lunches = await repo.bell_schedule.get_context()
    await cb.message.edit_text(format_bell(bell, lunches), reply_markup=BACK_KB)
    await cb.answer()


@user_router.callback_query(F.data == "hist")
async def cb_hist(cb: CallbackQuery, repo: RequestsRepo, user: User):
    if not await _require_group(cb, user):
        return
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
    if not await _require_group(cb, user):
        return
    date = datetime.date.fromisoformat(cb.data.split(":", 1)[1])
    bell, lunches = await repo.bell_schedule.get_context()
    lessons = await repo.college_lessons.get_for_group_date(user.group, date)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ К истории", callback_data="hist")],
        [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu")],
    ])
    await cb.message.edit_text(format_day(date, lessons, bell, lunches, user.bell_detail), reply_markup=kb)
    await cb.answer()


@user_router.callback_query(F.data == "sub:toggle")
async def cb_sub(cb: CallbackQuery, repo: RequestsRepo, user: User):
    if not await _require_group(cb, user):
        return
    new = not user.subscribed
    await repo.users.set_subscribed(user.id, new)
    await cb.message.edit_text(menu_text(user), reply_markup=menu_kb(new, user.bell_detail))
    await cb.answer("Подписка включена 🔔" if new else "Подписка отключена 🔕")


@user_router.callback_query(F.data == "detail")
async def cb_detail(cb: CallbackQuery, repo: RequestsRepo, user: User):
    cur = user.bell_detail if user.bell_detail in DETAIL_ORDER else DETAIL_ORDER[0]
    nxt = DETAIL_ORDER[(DETAIL_ORDER.index(cur) + 1) % len(DETAIL_ORDER)]
    await repo.users.set_bell_detail(user.id, nxt)
    await cb.message.edit_text(menu_text(user), reply_markup=menu_kb(user.subscribed, nxt))
    await cb.answer(f"Детализация: {DETAIL_LABELS[nxt]}")


@user_router.callback_query(F.data == "find")
async def cb_find(cb: CallbackQuery, user: User, state: FSMContext):
    if not await _require_group(cb, user):
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Отмена", callback_data="find:cancel")],
    ])
    await cb.message.edit_text("🔎 Напиши название предмета (например, «химия»):", reply_markup=kb)
    await state.set_state(SubjectSearch.waiting)
    await cb.answer()


@user_router.callback_query(F.data == "find:cancel")
async def cb_find_cancel(cb: CallbackQuery, user: User, state: FSMContext):
    await state.clear()
    await cb.message.edit_text(menu_text(user), reply_markup=menu_kb(user.subscribed, user.bell_detail))
    await cb.answer()


@user_router.message(SubjectSearch.waiting)
async def subject_answer(message: Message, repo: RequestsRepo, user: User, state: FSMContext):
    await state.clear()
    subj = message.text.strip()
    lessons = await repo.college_lessons.get_all_for_group(user.group)
    matched = [l for l in lessons if subj.casefold() in l.subject.casefold()]
    if not matched:
        await message.answer(f"По «{subj}» ничего не нашлось", reply_markup=BACK_KB)
        return
    results = matched[:5]
    bell, lunches = await repo.bell_schedule.get_context()
    by_date: dict[datetime.date, list] = {}
    for l in results:
        by_date.setdefault(l.date, []).append(l)
    parts = [
        format_day(d, by_date[d], bell, lunches, user.bell_detail)
        for d in sorted(by_date, reverse=True)
    ]
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


@user_router.message(F.text)
async def any_text(message: Message, repo: RequestsRepo, user: User):
    group = message.text.strip().upper()
    known = await repo.college_lessons.get_groups()
    if group in known:
        await repo.users.set_group(user.id, group)
        await message.answer(f"Твоя группа: <b>{group}</b>", reply_markup=menu_kb(user.subscribed, user.bell_detail))
    else:
        await message.answer(menu_text(user), reply_markup=menu_kb(user.subscribed, user.bell_detail))
