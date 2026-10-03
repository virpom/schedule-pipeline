import datetime

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from config import Config
from infrastructure.database.repo.requests import RequestsRepo

admin_router = Router()

VALID_DAY = {"MONDAY", "OTHER"}
VALID_COURSE = {"ALL", "I_IV", "II_III"}


def _is_admin(message: Message, config: Config) -> bool:
    return message.from_user.id in config.tg_bot.admin_ids


@admin_router.message(Command("bell"))
async def show_bell(message: Message, repo: RequestsRepo, config: Config):
    if not _is_admin(message, config):
        return
    bell = await repo.bell_schedule.get_all()
    lines = [
        f"{b.day_type} {b.course_group} п{b.para}: {b.start:%H:%M}–{b.end:%H:%M}"
        for b in sorted(bell, key=lambda x: (x.day_type, x.course_group, x.para))
    ]
    await message.answer("\n".join(lines) or "Звонки не заданы")


@admin_router.message(Command("setbell"))
async def set_bell(message: Message, repo: RequestsRepo, config: Config):
    if not _is_admin(message, config):
        return
    parts = message.text.split()
    if len(parts) != 5:
        await message.answer(
            "Формат: /setbell DAY_TYPE COURSE_GROUP PARA HH:MM-HH:MM\n"
            "Пример: /setbell MONDAY I_IV 1 09:25-10:10"
        )
        return

    day_type, course_group, para_s, time_s = parts[1].upper(), parts[2].upper(), parts[3], parts[4]

    if day_type not in VALID_DAY or course_group not in VALID_COURSE:
        await message.answer("DAY_TYPE: MONDAY|OTHER, COURSE_GROUP: ALL|I_IV|II_III")
        return

    try:
        para = int(para_s)
        start_s, end_s = time_s.split("-")
        start = datetime.time.fromisoformat(start_s)
        end = datetime.time.fromisoformat(end_s)
    except ValueError:
        await message.answer("Неверный формат. Пример: /setbell MONDAY I_IV 1 09:25-10:10")
        return

    await repo.bell_schedule.upsert(day_type, course_group, para, start, end)
    await message.answer(f"Сохранено: {day_type} {course_group} п{para} {start:%H:%M}–{end:%H:%M}")
