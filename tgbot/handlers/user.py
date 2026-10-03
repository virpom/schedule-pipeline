import datetime

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from common.schedule import format_bell, format_day, format_week
from infrastructure.database.models import User
from infrastructure.database.repo.requests import RequestsRepo

user_router = Router()

BACK_KB = InlineKeyboardMarkup(
    inline_keyboard=[[InlineKeyboardButton(text="⬅️ В меню", callback_data="menu")]]
)


def menu_kb(subscribed: bool) -> InlineKeyboardMarkup:
    sub_text = "🔕 Отписаться" if subscribed else "🔔 Подписаться"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Сегодня", callback_data="day:today"),
         InlineKeyboardButton(text="📅 Завтра", callback_data="day:tomorrow")],
        [InlineKeyboardButton(text="🗓 Вся неделя", callback_data="week"),
         InlineKeyboardButton(text="⏰ Звонки", callback_data="bell")],
        [InlineKeyboardButton(text=sub_text, callback_data="sub:toggle")],
        [InlineKeyboardButton(text="🎯 Сменить группу", callback_data="pick")],
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
async def start(message: Message, user: User, repo: RequestsRepo):
    if user.group:
        await message.answer(menu_text(user), reply_markup=menu_kb(user.subscribed))
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
    await message.answer(f"Твоя группа: <b>{group}</b>", reply_markup=menu_kb(user.subscribed))


@user_router.callback_query(F.data == "pick")
async def cb_pick(cb: CallbackQuery, repo: RequestsRepo):
    await cb.message.edit_text("Выбери свою группу 👇", reply_markup=await _pick_kb(repo))
    await cb.answer()


@user_router.callback_query(F.data.startswith("group:"))
async def cb_group(cb: CallbackQuery, repo: RequestsRepo, user: User):
    group = cb.data.split(":", 1)[1]
    await repo.users.set_group(user.id, group)
    await cb.message.edit_text(f"Твоя группа: <b>{group}</b>", reply_markup=menu_kb(user.subscribed))
    await cb.answer(f"Группа {group}")


@user_router.callback_query(F.data == "menu")
async def cb_menu(cb: CallbackQuery, user: User):
    await cb.message.edit_text(menu_text(user), reply_markup=menu_kb(user.subscribed))
    await cb.answer()


async def _show_day(cb: CallbackQuery, repo: RequestsRepo, user: User, date: datetime.date):
    bell = await repo.bell_schedule.as_dict()
    lessons = await repo.college_lessons.get_for_group_date(user.group, date)
    if lessons:
        text = format_day(date, lessons, bell)
    else:
        text = format_day(date, [], bell)
        for i in range(1, 8):
            d = date + datetime.timedelta(days=i)
            nxt = await repo.college_lessons.get_for_group_date(user.group, d)
            if nxt:
                text += "\n\nБлижайшее —\n" + format_day(d, nxt, bell)
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
    bell = await repo.bell_schedule.as_dict()
    start = datetime.date.today()
    end = start + datetime.timedelta(days=6)
    lessons = await repo.college_lessons.get_for_group_range(user.group, start, end)
    by_date: dict[datetime.date, list] = {}
    for l in lessons:
        by_date.setdefault(l.date, []).append(l)
    entries = [(d, by_date[d]) for d in sorted(by_date)]
    await cb.message.edit_text(format_week(entries, bell), reply_markup=BACK_KB)
    await cb.answer()


@user_router.callback_query(F.data == "bell")
async def cb_bell(cb: CallbackQuery, repo: RequestsRepo):
    items = await repo.bell_schedule.get_all()
    await cb.message.edit_text(format_bell(items), reply_markup=BACK_KB)
    await cb.answer()


@user_router.callback_query(F.data == "sub:toggle")
async def cb_sub(cb: CallbackQuery, repo: RequestsRepo, user: User):
    if not await _require_group(cb, user):
        return
    new = not user.subscribed
    await repo.users.set_subscribed(user.id, new)
    await cb.message.edit_text(menu_text(user), reply_markup=menu_kb(new))
    await cb.answer("Подписка включена 🔔" if new else "Подписка отключена 🔕")


@user_router.message(F.text)
async def any_text(message: Message, repo: RequestsRepo, user: User):
    group = message.text.strip().upper()
    known = await repo.college_lessons.get_groups()
    if group in known:
        await repo.users.set_group(user.id, group)
        await message.answer(f"Твоя группа: <b>{group}</b>", reply_markup=menu_kb(user.subscribed))
    else:
        await message.answer(menu_text(user), reply_markup=menu_kb(user.subscribed))
