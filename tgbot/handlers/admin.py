import datetime

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from common.schedule import format_bell
from config import Config
from infrastructure.database.repo.requests import RequestsRepo

admin_router = Router()

VALID_DAY = {"MONDAY", "OTHER"}
VALID_COURSE = {"ALL", "I_IV", "II_III"}


def _is_admin(message: Message, config: Config) -> bool:
    return message.from_user.id in config.tg_bot.admin_ids


def _is_admin_cb(cb: CallbackQuery, config: Config) -> bool:
    return cb.from_user.id in config.tg_bot.admin_ids


@admin_router.message(Command("bell"))
async def show_bell(message: Message, repo: RequestsRepo, config: Config):
    if not _is_admin(message, config):
        return
    bell, lunches = await repo.bell_schedule.get_context()
    await message.answer(format_bell(bell, lunches))


async def _build_stats(repo: RequestsRepo) -> tuple[str, InlineKeyboardMarkup]:
    users = await repo.users.get_all()
    now = datetime.datetime.now()
    week_ago = now - datetime.timedelta(days=7)
    total = len(users)
    active = sum(1 for u in users if u.last_seen and u.last_seen >= week_ago)
    subscribed = sum(1 for u in users if u.subscribed)

    lessons = await repo.college_lessons.count_lessons()
    days = await repo.college_lessons.count_dates()
    groups = len(await repo.college_lessons.get_groups())

    group_stats: dict[str, list[int]] = {}
    no_group = [0, 0]
    for u in users:
        if u.group:
            entry = group_stats.setdefault(u.group, [0, 0])
            entry[0] += 1
            if u.subscribed:
                entry[1] += 1
        else:
            no_group[0] += 1
            if u.subscribed:
                no_group[1] += 1

    lines = ["👥 <b>Статистика</b>\n"]
    lines.append(f"Всего пользователей: <b>{total}</b>")
    lines.append(f"Активных (7 дней): <b>{active}</b>")
    lines.append(f"Подписаны на рассылку: <b>{subscribed}</b>")
    lines.append("")
    lines.append("📚 <b>Расписание в базе</b>")
    lines.append(f"Занятий: {lessons} · Дней: {days} · Групп: {groups}")
    lines.append("")
    lines.append("👥 <b>По группам</b> (нажми, чтобы раскрыть)")

    rows = []
    for g, (t, s) in sorted(group_stats.items(), key=lambda x: (-x[1][0], x[0])):
        rows.append([InlineKeyboardButton(text=f"{g} — {t} · рассылка {s}", callback_data=f"group_users:{g}")])
    if no_group[0]:
        rows.append([InlineKeyboardButton(text=f"Без группы — {no_group[0]} · рассылка {no_group[1]}", callback_data="group_users:__none__")])

    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


@admin_router.message(Command("stats"))
async def stats(message: Message, repo: RequestsRepo, config: Config):
    if not _is_admin(message, config):
        return
    text, kb = await _build_stats(repo)
    await message.answer(text, reply_markup=kb)


@admin_router.callback_query(lambda cb: cb.data == "admin_stats")
async def cb_admin_stats(cb: CallbackQuery, repo: RequestsRepo, config: Config):
    if not _is_admin_cb(cb, config):
        return
    text, kb = await _build_stats(repo)
    await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer()


@admin_router.callback_query(lambda cb: cb.data and cb.data.startswith("group_users:"))
async def cb_group_users(cb: CallbackQuery, repo: RequestsRepo, config: Config):
    if not _is_admin_cb(cb, config):
        return
    group = cb.data.split(":", 1)[1]
    if group == "__none__":
        users = await repo.users.get_by_group(None)
        title = "Без группы"
    else:
        users = await repo.users.get_by_group(group)
        title = group

    lines = [f"👥 <b>{title}</b> ({len(users)})\n"]
    for u in users:
        tag = f"@{u.username}" if u.username else str(u.id)
        line = f"{tag} — {u.full_name}"
        if u.subscribed:
            line += " 🔔"
        lines.append(line)
    if not users:
        lines.append("Никого нет")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад к статистике", callback_data="admin_stats")],
    ])
    await cb.message.edit_text("\n".join(lines), reply_markup=kb)
    await cb.answer()


@admin_router.message(Command("settings"))
async def settings_cmd(message: Message, repo: RequestsRepo, config: Config):
    if not _is_admin(message, config):
        return
    s = await repo.settings.get_all()
    night = "выключена"
    if s["night_start"] and s["night_end"] and s["night_start"] != s["night_end"]:
        night = f"{s['night_start']}–{s['night_end']}"
    await message.answer(
        "⚙️ <b>Настройки</b>\n\n"
        f"Интервал опроса: <b>{s['poll_interval']} сек</b>\n"
        f"Скорость рассылки: <b>{s['notify_rate']} сообщ/сек</b>\n"
        f"Ночная пауза: <b>{night}</b>"
    )


@admin_router.message(Command("setpoll"))
async def set_poll(message: Message, repo: RequestsRepo, config: Config):
    if not _is_admin(message, config):
        return
    parts = message.text.split()
    if len(parts) != 2:
        await message.answer("Формат: /setpoll 300")
        return
    try:
        sec = int(parts[1])
        if sec < 10:
            raise ValueError
    except ValueError:
        await message.answer("Интервал — целое число секунд (мин. 10)")
        return
    await repo.settings.set("poll_interval", str(sec))
    await message.answer(f"Интервал опроса: {sec} сек")


@admin_router.message(Command("setrate"))
async def set_rate(message: Message, repo: RequestsRepo, config: Config):
    if not _is_admin(message, config):
        return
    parts = message.text.split()
    if len(parts) != 2:
        await message.answer("Формат: /setrate 20")
        return
    try:
        rate = float(parts[1])
        if not 0 < rate <= 30:
            raise ValueError
    except ValueError:
        await message.answer("Скорость — число сообщений/сек (0–30)")
        return
    await repo.settings.set("notify_rate", str(rate))
    await message.answer(f"Скорость рассылки: {rate} сообщ/сек")


@admin_router.message(Command("setnight"))
async def set_night(message: Message, repo: RequestsRepo, config: Config):
    if not _is_admin(message, config):
        return
    parts = message.text.split()
    if len(parts) >= 2 and parts[1].lower() == "off":
        await repo.settings.set("night_start", "")
        await repo.settings.set("night_end", "")
        await message.answer("Ночная пауза выключена")
        return
    if len(parts) != 3:
        await message.answer("Формат: /setnight 23:00 07:00  (или /setnight off)")
        return
    try:
        datetime.time.fromisoformat(parts[1])
        datetime.time.fromisoformat(parts[2])
    except ValueError:
        await message.answer("Формат времени: HH:MM")
        return
    await repo.settings.set("night_start", parts[1])
    await repo.settings.set("night_end", parts[2])
    await message.answer(f"Ночная пауза: {parts[1]}–{parts[2]}")


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
