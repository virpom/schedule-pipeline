from collections.abc import Sequence

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from common.academic_calendar import WeekDay
from infrastructure.database.models import Lesson
from infrastructure.database.repo.requests import RequestsRepo

user_router = Router()

MONTHS = {
    1: "янв.",
    2: "фев.",
    3: "мар.",
    4: "апр.",
    5: "май",
    6: "июн.",
    7: "июл.",
    8: "авг.",
    9: "сен.",
    10: "окт.",
    11: "ноя.",
    12: "дек."
}


@user_router.message(CommandStart())
async def user_start(message: Message) -> None:
    await message.reply("Привет! Я бот расписания. Напиши номер группы, чтобы узнать расписание.")


@user_router.message()
async def get_classes(message: Message, repo: RequestsRepo) -> None:
    class_lessons: Sequence[Lesson] = await repo.lessons.get_classes_for_current_week(message.text)
    if not class_lessons:
        await message.reply("Нет информации о занятиях данной группы")
        return

    last_date = (0, 0)
    response = ""
    for class_lesson in class_lessons:
        start_time, end_time = class_lesson.start_time, class_lesson.end_time
        class_type = class_lesson.session_type.value.capitalize()[0]
        if (start_time.day, start_time.month) != last_date:
            response += f"\n<b>{start_time.day} {MONTHS[start_time.month]}, {WeekDay(start_time.weekday()).short_name}</b>\n"
            last_date = (start_time.day, start_time.month)
        response += f"> {start_time:%H:%M} - {end_time:%H:%M}: {class_lesson.title} ({class_type})\n"

    await message.reply(response)
