import datetime

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from common.schedule import format_day
from infrastructure.database.models import User
from infrastructure.database.repo.requests import RequestsRepo

user_router = Router()

HELP = (
    "Привет! Я бот расписания Политехнического колледжа ЗГУ.\n\n"
    "Установи группу: /group ТЭ-26ФП\n"
    "Дальше:\n"
    "/today — на сегодня\n"
    "/tomorrow — на завтра\n"
    "/subscribe — присылать расписание, когда его выложат\n"
    "/unsubscribe — отключить рассылку\n"
    "Или просто напиши номер группы."
)


async def _show_day(repo: RequestsRepo, group: str, date: datetime.date) -> str:
    bell = await repo.bell_schedule.as_dict()
    lessons = await repo.college_lessons.get_for_group_date(group, date)
    return format_day(date, lessons, bell)


@user_router.message(CommandStart())
async def start(message: Message):
    await message.answer(HELP)


@user_router.message(Command("help"))
async def help_cmd(message: Message):
    await message.answer(HELP)


@user_router.message(Command("group"))
async def set_group(message: Message, repo: RequestsRepo):
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Формат: /group ТЭ-26ФП")
        return
    group = parts[1].strip().upper()
    await repo.users.set_group(message.from_user.id, group)
    await message.answer(f"Группа установлена: {group}")


@user_router.message(Command("subscribe"))
async def subscribe(message: Message, repo: RequestsRepo, user: User):
    if not user.group:
        await message.answer("Сначала укажи группу: /group ТЭ-26ФП")
        return
    await repo.users.set_subscribed(user.id, True)
    await message.answer(f"Рассылка включена для группы {user.group}")


@user_router.message(Command("unsubscribe"))
async def unsubscribe(message: Message, repo: RequestsRepo, user: User):
    await repo.users.set_subscribed(user.id, False)
    await message.answer("Рассылка отключена")


@user_router.message(Command("today"))
async def today(message: Message, repo: RequestsRepo, user: User):
    if not user.group:
        await message.answer("Сначала укажи группу: /group ТЭ-26ФП")
        return
    await message.answer(await _show_day(repo, user.group, datetime.date.today()))


@user_router.message(Command("tomorrow"))
async def tomorrow(message: Message, repo: RequestsRepo, user: User):
    if not user.group:
        await message.answer("Сначала укажи группу: /group ТЭ-26ФП")
        return
    date = datetime.date.today() + datetime.timedelta(days=1)
    await message.answer(await _show_day(repo, user.group, date))


@user_router.message(F.text)
async def group_query(message: Message, repo: RequestsRepo):
    group = message.text.strip().upper()
    known = await repo.college_lessons.get_groups()
    if group not in known:
        await message.answer(f"Группа «{group}» не найдена в расписании")
        return
    today = datetime.date.today()
    text = await _show_day(repo, group, today)
    text += "\n\n" + await _show_day(repo, group, today + datetime.timedelta(days=1))
    await message.answer(text)
