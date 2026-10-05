import asyncio
import datetime
import os
import time

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from common.schedule import format_bell, format_day
from config import Config
from infrastructure.database.repo.requests import RequestsRepo
from tgbot.services import photos
from tgbot.services.broadcaster import broadcast_many
from tgbot.services.poller import notify_new_schedule

admin_router = Router()

VALID_DAY = {"MONDAY", "OTHER"}
VALID_COURSE = {"ALL", "I_IV", "II_III"}


class AdminState(StatesGroup):
    set_poll = State()
    set_rate = State()
    set_deadline = State()
    set_night = State()
    set_support = State()
    set_broadcast = State()
    confirm_broadcast = State()
    upload_photo = State()


def _is_admin(message: Message, config: Config) -> bool:
    return message.from_user.id in config.tg_bot.admin_ids


def _is_admin_cb(cb: CallbackQuery, config: Config) -> bool:
    return cb.from_user.id in config.tg_bot.admin_ids


def _settings_text(s: dict) -> str:
    night = "выключена"
    if s["night_start"] and s["night_end"] and s["night_start"] != s["night_end"]:
        night = f"{s['night_start']}–{s['night_end']}"
    return (
        "⚙️ <b>Настройки</b>\n\n"
        f"Интервал опроса: <b>{s['poll_interval']} сек</b>\n"
        f"Скорость рассылки: <b>{s['notify_rate']} сообщ/сек</b>\n"
        f"Ночная пауза: <b>{night}</b>\n"
        f"Дедлайн «занятий нет»: <b>{s['deadline_hour']}:00</b>\n"
        f"Ссылка поддержки: <b>{s['support_link'] or '—'}</b>"
    )


def _admin_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="adm:stats"),
         InlineKeyboardButton(text="⚙️ Настройки", callback_data="adm:settings")],
        [InlineKeyboardButton(text="🖼 Фото", callback_data="adm:photos"),
         InlineKeyboardButton(text="⏰ Звонки", callback_data="adm:bell")],
        [InlineKeyboardButton(text="📢 Сообщение всем", callback_data="adm:broadcast"),
         InlineKeyboardButton(text="🔔 Тест уведомления", callback_data="adm:notify")],
    ])


def _settings_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Интервал опроса", callback_data="adm:set_poll")],
        [InlineKeyboardButton(text="Скорость рассылки", callback_data="adm:set_rate")],
        [InlineKeyboardButton(text="Ночная пауза", callback_data="adm:set_night")],
        [InlineKeyboardButton(text="Дедлайн «занятий нет»", callback_data="adm:set_deadline")],
        [InlineKeyboardButton(text="Ссылка поддержки", callback_data="adm:set_support")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="adm:back")],
    ])


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
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="adm:back")])

    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


# ---- commands ----

@admin_router.message(Command("admin"))
async def admin_menu(message: Message, config: Config):
    if not _is_admin(message, config):
        return
    await message.answer("⚙️ <b>Админ-меню</b>\n\nВыбери раздел 👇", reply_markup=_admin_kb())


@admin_router.message(Command("bell"))
async def show_bell(message: Message, repo: RequestsRepo, config: Config):
    if not _is_admin(message, config):
        return
    bell, lunches = await repo.bell_schedule.get_context()
    await message.answer(format_bell(bell, lunches))


@admin_router.message(Command("stats"))
async def stats(message: Message, repo: RequestsRepo, config: Config):
    if not _is_admin(message, config):
        return
    text, kb = await _build_stats(repo)
    await message.answer(text, reply_markup=kb)


@admin_router.message(Command("settings"))
async def settings_cmd(message: Message, repo: RequestsRepo, config: Config):
    if not _is_admin(message, config):
        return
    s = await repo.settings.get_all()
    await message.answer(_settings_text(s), reply_markup=_settings_kb())


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


@admin_router.message(Command("setgroup"))
async def set_chat_group(message: Message, repo: RequestsRepo, config: Config):
    if not _is_admin(message, config):
        return
    if message.chat.type not in ("group", "supergroup"):
        await message.answer("Команда для группового чата: добавь бота в чат и введи /setgroup <группа>")
        return
    parts = message.text.split()
    if len(parts) != 2:
        await message.answer("Формат: /setgroup ДП-26")
        return
    group = parts[1].strip().upper()
    await repo.chats.set_group(message.chat.id, message.chat.title or "", group)
    await message.answer(f"Группа чата: <b>{group}</b>. Сюда будет приходить расписание.")


@admin_router.message(Command("chats"))
async def list_chats(message: Message, repo: RequestsRepo, config: Config):
    if not _is_admin(message, config):
        return
    chats = await repo.chats.get_all()
    if not chats:
        await message.answer("Чатов пока нет")
        return
    lines = ["💬 <b>Чаты</b>\n"]
    for c in chats:
        lines.append(f"{c.id} · {c.title or '—'} → {c.group or '—'}")
    await message.answer("\n".join(lines))


async def _send_preview(message: Message, repo: RequestsRepo, config: Config, date, group: str):
    bell, lunches = await repo.bell_schedule.get_context()
    lessons = await repo.college_lessons.get_for_group_date(group, date)
    text = format_day(date, lessons, bell, lunches, "brief")
    photo = photos.random_photo(config.photos_path, photos.weekday_folder(date))
    if photo:
        await message.bot.send_photo(message.chat.id, photo, caption=text)
    else:
        await message.answer(text)


async def _report_broadcast(bot, chat_id, items, rate):
    sent = await broadcast_many(bot, items, rate=rate)
    try:
        await bot.send_message(chat_id, f"Готово: отправлено {sent}/{len(items)}")
    except Exception:
        pass


async def _confirm_broadcast(message: Message, repo: RequestsRepo, state: FSMContext, text: str):
    users = await repo.users.get_all()
    await state.update_data(broadcast_text=text)
    await state.set_state(AdminState.confirm_broadcast)
    preview = text if len(text) <= 400 else text[:400] + "…"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Отправить всем", callback_data="adm:bc_send"),
         InlineKeyboardButton(text="❌ Отмена", callback_data="adm:bc_cancel")],
    ])
    await message.answer(f"Отправить <b>{len(users)}</b> пользователям?\n\n{preview}", reply_markup=kb)


@admin_router.message(Command("broadcast"))
async def broadcast_cmd(message: Message, repo: RequestsRepo, config: Config, state: FSMContext):
    if not _is_admin(message, config):
        return
    parts = message.text.split(None, 1)
    if len(parts) < 2:
        await state.set_state(AdminState.set_broadcast)
        await message.answer("Введи текст сообщения для всех:")
        return
    await _confirm_broadcast(message, repo, state, parts[1])


def _notify_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔔 Всем подписчикам", callback_data="adm:notify_all")],
        [InlineKeyboardButton(text="👤 Себе (превью)", callback_data="adm:notify_me")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="adm:back")],
    ])


@admin_router.message(Command("notify"))
async def notify_cmd(message: Message, repo: RequestsRepo, config: Config, user):
    if not _is_admin(message, config):
        return
    parts = message.text.split()
    if len(parts) >= 2:
        latest = await repo.college_lessons.get_latest_date()
        if not latest:
            await message.answer("В базе нет расписания")
            return
        arg = parts[1]
        if arg.lower() == "me":
            if not user.group:
                await message.answer("У тебя не выбрана группа")
                return
            await _send_preview(message, repo, config, latest, user.group)
        else:
            await _send_preview(message, repo, config, latest, arg.upper())
        return
    await message.answer("🔔 <b>Тест уведомления</b>\n\nКому отправить?", reply_markup=_notify_menu_kb())


@admin_router.callback_query(lambda cb: cb.data == "adm:broadcast")
async def cb_broadcast(cb: CallbackQuery, config: Config, state: FSMContext):
    if not _is_admin_cb(cb, config):
        return
    await state.set_state(AdminState.set_broadcast)
    await cb.message.answer("Введи текст сообщения для всех:")
    await cb.answer()


@admin_router.callback_query(lambda cb: cb.data == "adm:notify")
async def cb_notify_menu(cb: CallbackQuery, config: Config):
    if not _is_admin_cb(cb, config):
        return
    await cb.message.edit_text("🔔 <b>Тест уведомления</b>\n\nКому отправить?", reply_markup=_notify_menu_kb())
    await cb.answer()


@admin_router.callback_query(lambda cb: cb.data == "adm:notify_all")
async def cb_notify_all(cb: CallbackQuery, config: Config):
    if not _is_admin_cb(cb, config):
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, отправить всем", callback_data="adm:notify_confirm")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="adm:notify_cancel")],
    ])
    await cb.message.edit_text("Отправить расписание всем подписчикам и чатам?", reply_markup=kb)
    await cb.answer()


@admin_router.callback_query(lambda cb: cb.data == "adm:notify_confirm")
async def cb_notify_confirm(cb: CallbackQuery, repo: RequestsRepo, config: Config, session_pool):
    if not _is_admin_cb(cb, config):
        return
    latest = await repo.college_lessons.get_latest_date()
    if not latest:
        await cb.answer("В базе нет расписания")
        return
    await cb.message.edit_text("Рассылка запущена")
    await cb.answer()
    rate = float((await repo.settings.get_all())["notify_rate"])
    asyncio.create_task(notify_new_schedule(cb.message.bot, session_pool, [latest], rate, config.photos_path))


@admin_router.callback_query(lambda cb: cb.data == "adm:notify_cancel")
async def cb_notify_cancel(cb: CallbackQuery, config: Config):
    if not _is_admin_cb(cb, config):
        return
    await cb.message.edit_text("Отменено")
    await cb.answer()


@admin_router.callback_query(lambda cb: cb.data == "adm:notify_me")
async def cb_notify_me(cb: CallbackQuery, repo: RequestsRepo, config: Config, user):
    if not _is_admin_cb(cb, config):
        return
    latest = await repo.college_lessons.get_latest_date()
    if not latest:
        await cb.answer("В базе нет расписания")
        return
    if not user.group:
        await cb.answer("У тебя не выбрана группа")
        return
    await cb.answer()
    await _send_preview(cb.message, repo, config, latest, user.group)


@admin_router.message(AdminState.set_broadcast)
async def m_broadcast(message: Message, repo: RequestsRepo, state: FSMContext):
    await _confirm_broadcast(message, repo, state, message.text.strip())


@admin_router.callback_query(lambda cb: cb.data == "adm:bc_send")
async def cb_bc_send(cb: CallbackQuery, repo: RequestsRepo, config: Config, state: FSMContext):
    if not _is_admin_cb(cb, config):
        return
    data = await state.get_data()
    text = data.get("broadcast_text")
    await state.clear()
    if not text:
        await cb.answer("Нет текста")
        return
    users = await repo.users.get_all()
    rate = float((await repo.settings.get_all())["notify_rate"])
    items = [(u.id, text) for u in users]
    await cb.message.edit_text(f"Рассылка запущена ({len(items)} получателей)")
    await cb.answer()
    asyncio.create_task(_report_broadcast(cb.message.bot, cb.message.chat.id, items, rate))


@admin_router.callback_query(lambda cb: cb.data == "adm:bc_cancel")
async def cb_bc_cancel(cb: CallbackQuery, config: Config, state: FSMContext):
    if not _is_admin_cb(cb, config):
        return
    await state.clear()
    await cb.message.edit_text("Отменено")
    await cb.answer()


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


# ---- admin callbacks ----

@admin_router.callback_query(lambda cb: cb.data == "adm:back")
async def cb_adm_back(cb: CallbackQuery, config: Config):
    if not _is_admin_cb(cb, config):
        return
    await cb.message.edit_text("⚙️ <b>Админ-меню</b>\n\nВыбери раздел 👇", reply_markup=_admin_kb())
    await cb.answer()


@admin_router.callback_query(lambda cb: cb.data == "adm:stats")
async def cb_adm_stats(cb: CallbackQuery, repo: RequestsRepo, config: Config):
    if not _is_admin_cb(cb, config):
        return
    text, kb = await _build_stats(repo)
    await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer()


@admin_router.callback_query(lambda cb: cb.data == "adm:settings")
async def cb_adm_settings(cb: CallbackQuery, repo: RequestsRepo, config: Config):
    if not _is_admin_cb(cb, config):
        return
    s = await repo.settings.get_all()
    await cb.message.edit_text(_settings_text(s), reply_markup=_settings_kb())
    await cb.answer()


@admin_router.callback_query(lambda cb: cb.data == "adm:bell")
async def cb_adm_bell(cb: CallbackQuery, repo: RequestsRepo, config: Config):
    if not _is_admin_cb(cb, config):
        return
    bell, lunches = await repo.bell_schedule.get_context()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="adm:back")],
    ])
    await cb.message.edit_text(format_bell(bell, lunches), reply_markup=kb)
    await cb.answer()


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
        [InlineKeyboardButton(text="⬅️ Назад к статистике", callback_data="adm:stats")],
    ])
    await cb.message.edit_text("\n".join(lines), reply_markup=kb)
    await cb.answer()


# ---- settings editing via prompts ----

@admin_router.callback_query(lambda cb: cb.data == "adm:set_poll")
async def cb_set_poll(cb: CallbackQuery, config: Config, state: FSMContext):
    if not _is_admin_cb(cb, config):
        return
    await state.set_state(AdminState.set_poll)
    await cb.message.answer("Введи интервал опроса (секунд, мин. 10):")
    await cb.answer()


@admin_router.callback_query(lambda cb: cb.data == "adm:set_rate")
async def cb_set_rate(cb: CallbackQuery, config: Config, state: FSMContext):
    if not _is_admin_cb(cb, config):
        return
    await state.set_state(AdminState.set_rate)
    await cb.message.answer("Введи скорость рассылки (сообщений/сек, 0–30):")
    await cb.answer()


@admin_router.callback_query(lambda cb: cb.data == "adm:set_deadline")
async def cb_set_deadline(cb: CallbackQuery, config: Config, state: FSMContext):
    if not _is_admin_cb(cb, config):
        return
    await state.set_state(AdminState.set_deadline)
    await cb.message.answer("Введи час дедлайна (0–23) или «off»:")
    await cb.answer()


@admin_router.callback_query(lambda cb: cb.data == "adm:set_night")
async def cb_set_night(cb: CallbackQuery, config: Config, state: FSMContext):
    if not _is_admin_cb(cb, config):
        return
    await state.set_state(AdminState.set_night)
    await cb.message.answer("Введи ночное окно «HH:MM HH:MM» или «off»:")
    await cb.answer()


@admin_router.callback_query(lambda cb: cb.data == "adm:set_support")
async def cb_set_support(cb: CallbackQuery, config: Config, state: FSMContext):
    if not _is_admin_cb(cb, config):
        return
    await state.set_state(AdminState.set_support)
    await cb.message.answer("Отправь ссылку на группу поддержки:")
    await cb.answer()


@admin_router.message(AdminState.set_poll)
async def m_set_poll(message: Message, repo: RequestsRepo, state: FSMContext):
    await state.clear()
    try:
        sec = int(message.text.strip())
        if sec < 10:
            raise ValueError
    except ValueError:
        await message.answer("Неверно. Целое число секунд (мин. 10).")
        return
    await repo.settings.set("poll_interval", str(sec))
    await message.answer(f"Интервал опроса: {sec} сек")


@admin_router.message(AdminState.set_rate)
async def m_set_rate(message: Message, repo: RequestsRepo, state: FSMContext):
    await state.clear()
    try:
        rate = float(message.text.strip())
        if not 0 < rate <= 30:
            raise ValueError
    except ValueError:
        await message.answer("Неверно. Число 0–30.")
        return
    await repo.settings.set("notify_rate", str(rate))
    await message.answer(f"Скорость рассылки: {rate} сообщ/сек")


@admin_router.message(AdminState.set_deadline)
async def m_set_deadline(message: Message, repo: RequestsRepo, state: FSMContext):
    await state.clear()
    raw = message.text.strip().lower()
    if raw == "off":
        await repo.settings.set("deadline_hour", "-1")
        await message.answer("Дедлайн отключён (всегда «ещё не выложено» до появления файла)")
        return
    try:
        h = int(raw)
        if not 0 <= h <= 23:
            raise ValueError
    except ValueError:
        await message.answer("Неверно. Час 0–23 или «off».")
        return
    await repo.settings.set("deadline_hour", str(h))
    await message.answer(f"Дедлайн «занятий нет»: {h}:00")


@admin_router.message(AdminState.set_night)
async def m_set_night(message: Message, repo: RequestsRepo, state: FSMContext):
    await state.clear()
    raw = message.text.strip()
    if raw.lower() == "off":
        await repo.settings.set("night_start", "")
        await repo.settings.set("night_end", "")
        await message.answer("Ночная пауза выключена")
        return
    parts = raw.split()
    if len(parts) != 2:
        await message.answer("Формат: «HH:MM HH:MM» или «off»")
        return
    try:
        datetime.time.fromisoformat(parts[0])
        datetime.time.fromisoformat(parts[1])
    except ValueError:
        await message.answer("Формат времени: HH:MM")
        return
    await repo.settings.set("night_start", parts[0])
    await repo.settings.set("night_end", parts[1])
    await message.answer(f"Ночная пауза: {parts[0]}–{parts[1]}")


@admin_router.message(AdminState.set_support)
async def m_set_support(message: Message, repo: RequestsRepo, state: FSMContext):
    await state.clear()
    link = message.text.strip()
    await repo.settings.set("support_link", link)
    await message.answer(f"Ссылка поддержки: {link}")


# ---- photo management ----

def _photo_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Загрузить фото", callback_data="adm:photo_upload")],
        [InlineKeyboardButton(text="📋 Список фото", callback_data="adm:photo_list")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="adm:back")],
    ])


def _weekday_kb(prefix: str = "phday") -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=label, callback_data=f"{prefix}:{wd}")]
        for wd, label in zip(photos.WEEKDAYS, ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"])
    ]
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="adm:photos")])
    return InlineKeyboardMarkup(inline_keyboard=[rows[0], rows[1], rows[2], rows[3], rows[4], rows[5], rows[6]])


@admin_router.callback_query(lambda cb: cb.data == "adm:photos")
async def cb_adm_photos(cb: CallbackQuery, config: Config):
    if not _is_admin_cb(cb, config):
        return
    await cb.message.edit_text("🖼 <b>Фото</b>\n\nЗагружай картинки по дням недели — они прикладываются к уведомлениям.", reply_markup=_photo_menu_kb())
    await cb.answer()


@admin_router.callback_query(lambda cb: cb.data == "adm:photo_upload")
async def cb_photo_upload(cb: CallbackQuery, config: Config):
    if not _is_admin_cb(cb, config):
        return
    await cb.message.edit_text("Выбери день недели 👇", reply_markup=_weekday_kb())
    await cb.answer()


@admin_router.callback_query(lambda cb: cb.data and cb.data.startswith("phday:"))
async def cb_photo_day(cb: CallbackQuery, config: Config, state: FSMContext):
    if not _is_admin_cb(cb, config):
        return
    weekday = cb.data.split(":", 1)[1]
    await state.update_data(weekday=weekday)
    await state.set_state(AdminState.upload_photo)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Готово", callback_data="adm:photo_done")],
    ])
    await cb.message.edit_text(f"Присылай фото для «{weekday}» (можно пачкой). Когда закончишь — ✅ Готово.", reply_markup=kb)
    await cb.answer()


@admin_router.callback_query(lambda cb: cb.data == "adm:photo_done")
async def cb_photo_done(cb: CallbackQuery, config: Config, state: FSMContext):
    if not _is_admin_cb(cb, config):
        return
    await state.clear()
    await cb.message.edit_text("Готово! Фото сохранены.", reply_markup=_photo_menu_kb())
    await cb.answer()


@admin_router.message(AdminState.upload_photo, F.photo)
async def upload_photo(message: Message, state: FSMContext, config: Config):
    data = await state.get_data()
    weekday = data.get("weekday", "monday")
    d = os.path.join(config.photos_path, weekday)
    os.makedirs(d, exist_ok=True)
    filename = f"{int(time.time())}_{message.photo[-1].file_unique_id}.jpg"
    await message.bot.download(message.photo[-1], destination=os.path.join(d, filename))
    await message.answer(f"✅ Сохранено в {weekday}")


@admin_router.callback_query(lambda cb: cb.data == "adm:photo_list")
async def cb_photo_list(cb: CallbackQuery, config: Config):
    if not _is_admin_cb(cb, config):
        return
    lines = ["🖼 <b>Фото по дням</b>\n"]
    for wd, label in zip(photos.WEEKDAYS, ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]):
        n = len(photos.list_photos(config.photos_path, wd))
        lines.append(f"{label}: {n}")
    lines.append("\nПапки на сервере: <code>{photos_path}/&lt;день&gt;/</code>".replace("{photos_path}", config.photos_path))
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="adm:photos")],
    ])
    await cb.message.edit_text("\n".join(lines), reply_markup=kb)
    await cb.answer()
