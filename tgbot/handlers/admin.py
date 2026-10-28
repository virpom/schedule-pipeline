import asyncio
import datetime
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Callable

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, Message

from common.schedule import (bells_group, format_bell, format_day, is_vuz,
                             strip_unit)
from config import Config
from infrastructure.database.repo.requests import RequestsRepo
from tgbot.services import photos, source_state
from tgbot.services.broadcaster import broadcast_many
from tgbot.services.poller import notify_new_schedule

admin_router = Router()

VALID_DAY = {"MONDAY", "OTHER"}
# VUZ — сетка вуза (8 пар). Без неё /setbell не мог править её вообще,
# хотя в базе эти строки есть и replace_bells их бережёт.
VALID_COURSE = {"ALL", "I_IV", "II_III", "VUZ"}


class AdminState(StatesGroup):
    set_poll = State()
    set_rate = State()
    set_night = State()
    set_support = State()
    set_broadcast = State()
    set_group_broadcast = State()
    confirm_broadcast = State()
    upload_photo = State()
    set_editor = State()


# Рассылки живут дольше обработчика, поэтому запускаются задачами. Ссылку
# надо держать: asyncio хранит только слабую, и без этого задача может быть
# собрана сборщиком мусора прямо во время отправки.
_background: set[asyncio.Task] = set()


def _spawn(coro) -> None:
    task = asyncio.create_task(coro)
    _background.add(task)

    def _done(t: asyncio.Task) -> None:
        _background.discard(t)
        if not t.cancelled() and t.exception() is not None:
            logging.exception("фоновая рассылка упала", exc_info=t.exception())

    task.add_done_callback(_done)


def _is_admin(message: Message, config: Config) -> bool:
    return message.from_user.id in config.tg_bot.admin_ids


def _is_admin_cb(cb: CallbackQuery, config: Config) -> bool:
    return cb.from_user.id in config.tg_bot.admin_ids


def _parse_hhmm(value: str) -> datetime.time | None:
    """Разобрать время строго как HH:MM.

    ``time.fromisoformat`` принимает больше, чем «HH:MM»: «23»,
    «07:00:00», «23:00+03:00». Последнее особенно опасно — с часовым
    поясом получается aware-время, и ``_in_night`` падает с TypeError
    на сравнении с naive ``now``. Поллер это ловит общим except, пишет
    «poll failed» и крутится, но ``poll_once`` не вызывается никогда:
    расписание замирает, пока админ не вспомнит про /setnight.

    Проверяем формат строкой, а не только результат разбора: «07:00:00»
    даёт ``time(7, 0)`` с нулевыми секундами, и по полям его от
    «07:00» не отличить.
    """
    if not re.fullmatch(r"\d{2}:\d{2}", value):
        return None
    try:
        return datetime.time.fromisoformat(value)
    except ValueError:
        return None


def _settings_text(s: dict) -> str:
    night = "выключена"
    if s["night_start"] and s["night_end"] and s["night_start"] != s["night_end"]:
        night = f"{s['night_start']}–{s['night_end']}"
    return (
        "⚙️ <b>Настройки</b>\n\n"
        f"Интервал опроса: <b>{s['poll_interval']} сек</b>\n"
        f"Скорость рассылки: <b>{s['notify_rate']} сообщ/сек</b>\n"
        f"Ночная пауза: <b>{night}</b>\n"
        f"Ссылка поддержки: <b>{s['support_link'] or '—'}</b>"
    )


def _admin_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="adm:stats"),
         InlineKeyboardButton(text="👨‍🏫 Преподаватели", callback_data="adm:teachers")],
        [InlineKeyboardButton(text="⚙️ Настройки", callback_data="adm:settings"),
         InlineKeyboardButton(text="⏰ Звонки", callback_data="adm:bell")],
        [InlineKeyboardButton(text="🖼 Фото", callback_data="adm:photos"),
         InlineKeyboardButton(text="💬 Чаты", callback_data="adm:chats")],
        [InlineKeyboardButton(text="✏️ Редакторы", callback_data="adm:editors"),
         InlineKeyboardButton(text="📢 Рассылка", callback_data="adm:broadcast_menu")],
        [InlineKeyboardButton(text="🔔 Тест уведомления", callback_data="adm:notify")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu")],
    ])


def _settings_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Интервал опроса", callback_data="adm:set:poll")],
        [InlineKeyboardButton(text="Скорость рассылки", callback_data="adm:set:rate")],
        [InlineKeyboardButton(text="Ночная пауза", callback_data="adm:set:night")],
        [InlineKeyboardButton(text="Ссылка поддержки", callback_data="adm:set:support")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="adm:back")],
    ])


async def _build_stats(repo: RequestsRepo) -> tuple[str, InlineKeyboardMarkup]:
    """Сводка по боту с разделением на колледж и вуз.

    Раньше всё считалось в кучу: 129 групп, общее число пар, общая
    аудитория. По такой цифре нельзя понять, где проблема — в вузе или
    в колледже, — а источники у них разные и ломаются независимо.
    """
    users = await repo.users.get_all()
    now = datetime.datetime.now()
    week_ago = now - datetime.timedelta(days=7)

    # Преподаватели не относятся ни к одному подразделению: у них нет
    # группы, а is_vuz(None) == False записал бы их в колледж.
    students = [u for u in users if u.role != "teacher"]
    vuz_users = [u for u in students if is_vuz(u.group)]
    college_users = [u for u in students if not is_vuz(u.group)]
    teachers = [u for u in users if u.role == "teacher"]
    subscribed = sum(1 for u in users if u.subscribed)
    active = sum(1 for u in users if u.last_seen and u.last_seen >= week_ago)

    groups = await repo.college_lessons.get_groups()
    vuz_groups = [g for g in groups if is_vuz(g)]
    college_groups = [g for g in groups if not is_vuz(g)]

    # Считаем по подразделению группы, а не по source: у колледжа
    # source='site', у вуза — 'vuz'. Привязка к source сломалась бы при
    # смене источника.
    base_vuz = await repo.base_lessons.count(vuz=True)
    base_college = await repo.base_lessons.count(vuz=False)
    subs_vuz = await repo.substitutions.count(vuz=True)
    subs_college = await repo.substitutions.count(vuz=False)

    lines = ["📊 <b>Статистика</b>\n"]
    lines.append(f"👥 Пользователей: <b>{len(users)}</b> · "
                 f"активных (7д): <b>{active}</b> · подписаны: <b>{subscribed}</b>")
    lines.append("")
    lines.append("<b>Подразделения</b>")
    lines.append(f"🎓 Колледж — студентов <b>{len(college_users)}</b>, "
                 f"групп <b>{len(college_groups)}</b>")
    lines.append(f"🏛 Вуз — студентов <b>{len(vuz_users)}</b>, "
                 f"групп <b>{len(vuz_groups)}</b>")
    if teachers:
        lines.append(f"👨‍🏫 Преподавателей: <b>{len(teachers)}</b>")
    lines.append("")
    lines.append("<b>Расписание</b>")
    lines.append(f"🎓 Колледж: пар <b>{base_college}</b> · замен <b>{subs_college}</b>")
    lines.append(f"🏛 Вуз: пар <b>{base_vuz}</b> · замен <b>{subs_vuz}</b>")
    lines.append("")

    # Источники независимы: ЭИОС может лежать, а файл вуза быть свежим.
    ok_college = await source_state.last_ok(repo)
    if await source_state.is_stale(repo):
        when = f"с {ok_college:%d.%m %H:%M}" if ok_college else "никогда"
        lines.append(f"⚠️ <b>ЭИОС колледжа не отвечает</b> (успех: {when})")
    elif ok_college:
        lines.append(f"✅ ЭИОС колледжа: {ok_college:%d.%m %H:%M}")

    ok_vuz = await source_state.last_ok_vuz(repo)
    if await source_state.is_stale_vuz(repo):
        when = f"с {ok_vuz:%d.%m %H:%M}" if ok_vuz else "ещё не было"
        lines.append(f"⚠️ <b>Синхронизация вуза не проходила</b> ({when})")
    elif ok_vuz:
        lines.append(f"✅ Вуз: {ok_vuz:%d.%m %H:%M}")

    rows = [
        [InlineKeyboardButton(text="🎓 Колледж подробно", callback_data="adm:stats:college"),
         InlineKeyboardButton(text="🏛 Вуз подробно", callback_data="adm:stats:vuz")],
        [InlineKeyboardButton(text="👥 Все группы", callback_data="adm:stats:groups")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="adm:back")],
    ]
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


async def _build_stats_unit(repo: RequestsRepo, unit: str) -> tuple[str, InlineKeyboardMarkup]:
    """Подробности по одному подразделению."""
    is_v = unit == "vuz"
    users = await repo.users.get_all()
    # Только студенты: у преподавателя группы нет, и он попадал бы
    # в колледж.
    students = [u for u in users if u.role != "teacher"]
    mine = [u for u in students if is_vuz(u.group) == is_v]
    subscribed = sum(1 for u in mine if u.subscribed)

    groups = [g for g in await repo.college_lessons.get_groups() if is_vuz(g) == is_v]
    base = await repo.base_lessons.count(vuz=is_v)
    subs = await repo.substitutions.count(vuz=is_v)

    title = "🏛 Вуз" if is_v else "🎓 Колледж"
    lines = [f"{title} — подробно\n"]
    lines.append(f"Студентов: <b>{len(mine)}</b> · подписаны: <b>{subscribed}</b>")
    lines.append(f"Групп в расписании: <b>{len(groups)}</b>")
    lines.append(f"Пар в базе: <b>{base}</b> · замен: <b>{subs}</b>")

    if is_v:
        info = await repo.vuz_groups.all()
        by_form: dict[str, int] = {}
        for g in info:
            by_form[g.form] = by_form.get(g.form, 0) + 1
        if by_form:
            names = {"full": "очная", "part": "очно-заочная"}
            parts = ", ".join(f"{names.get(k, k)} {v}" for k, v in sorted(by_form.items()))
            lines.append(f"Формы обучения: {parts}")

    # Топ групп по числу студентов.
    per_group: dict[str, int] = {}
    for u in mine:
        if u.group:
            per_group[u.group] = per_group.get(u.group, 0) + 1
    if per_group:
        lines.append("")
        lines.append("<b>Крупнейшие группы</b>")
        for g, n in sorted(per_group.items(), key=lambda x: -x[1])[:8]:
            lines.append(f"  {strip_unit(g)} — {n}")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ К статистике", callback_data="adm:stats")],
    ])
    return "\n".join(lines), kb


async def _build_stats_groups(repo: RequestsRepo) -> tuple[str, InlineKeyboardMarkup]:
    """Список всех групп с числом студентов — нажатием открыть состав."""
    users = await repo.users.get_all()
    per_group: dict[str, list[int]] = {}
    for u in users:
        if u.role == "teacher" or not u.group:
            continue
        e = per_group.setdefault(u.group, [0, 0])
        e[0] += 1
        if u.subscribed:
            e[1] += 1

    rows = []
    for g, (t, s) in sorted(per_group.items(), key=lambda x: (is_vuz(x[0]), x[0])):
        icon = "🏛" if is_vuz(g) else "🎓"
        rows.append([InlineKeyboardButton(
            text=f"{icon} {strip_unit(g)} — {t} · рассылка {s}",
            callback_data=f"group_users:{g}")])
    rows.append([InlineKeyboardButton(text="⬅️ К статистике", callback_data="adm:stats")])

    vuz_n = sum(1 for g in per_group if is_vuz(g))
    text = (f"👥 <b>Группы с подписчиками</b>\n\n"
            f"Всего <b>{len(per_group)}</b>: "
            f"🏛 вуз {vuz_n} · 🎓 колледж {len(per_group) - vuz_n}\n\n"
            "Нажми на группу, чтобы посмотреть состав.")
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


# ---- commands ----

@admin_router.message(Command("admin"))
async def admin_menu(message: Message, config: Config):
    if not _is_admin(message, config):
        return
    await message.answer("⚙️ <b>Админ-меню</b>\n\nВыбери раздел 👇", reply_markup=_admin_kb())


@admin_router.message(Command("setvuzanchor"))
async def set_vuz_anchor(message: Message, repo: RequestsRepo, config: Config):
    """Задать якорь учебной недели вуза вручную.

    Нужен, когда вуз меняет нумерацию недель (новый семестр): без этого
    расписание вуза поедет, и заметить это можно только глазами.
    Формат: /setvuzanchor 2027-02-08
    """
    if not _is_admin(message, config):
        return
    from tgbot.services import sync_vuz

    parts = (message.text or "").split()
    if len(parts) < 2:
        anchor = await sync_vuz.get_anchor(repo)
        await message.answer(
            f"Якорь недели вуза: <b>{anchor}</b>\n\n"
            "Задать новый: <code>/setvuzanchor 2027-02-08</code>\n"
            "Это дата первого дня первой учебной недели.")
        return
    try:
        value = datetime.date.fromisoformat(parts[1])
    except ValueError:
        await message.answer("Не понял дату. Нужен формат <code>2027-02-08</code>.")
        return
    # fromisoformat проверяет формат, но не смысл: /setvuzanchor 1999-01-01
    # принимался, vuz_week() возвращал неделю вроде 1400, ни одна пара не
    # совпадала, и расписание вуза молча пустело.
    today = datetime.date.today()
    if not (today - datetime.timedelta(days=400) <= value
            <= today + datetime.timedelta(days=400)):
        await message.answer(
            "Якорь должен быть в пределах учебного года от сегодня "
            f"({today - datetime.timedelta(days=400)} … "
            f"{today + datetime.timedelta(days=400)}).")
        return
    await sync_vuz.set_anchor(repo, value)
    # Пересборка сразу: иначе студент видит старое расписание до
    # следующего прохода поллера (5 минут), а если сайт лежит — до
    # бесконечности, и админ считает, что якорь применился.
    from tgbot.services import sync_eios
    try:
        await sync_eios.materialize(repo)
        tail = "Расписание пересобрано."
    except Exception as exc:  # noqa: BLE001 — админ должен узнать
        logging.exception("пересборка после смены якоря вуза упала")
        tail = (f"Пересобрать не удалось ({exc}). Поллер попробует "
                "снова в ближайшие 5 минут.")
    await message.answer(
        f"✅ Якорь вуза: <b>{value}</b>\n\n{tail}\n"
        "Если недели не сойдутся, в логе появится ошибка.")


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
    except ValueError:
        await message.answer("Интервал — целое число секунд (10 … 86400)")
        return
    # Верхняя граница: /setpoll 999999999 принимался, и poller_loop больше
    # никогда не опрашивал сайт — расписание замирало молча.
    if not 10 <= sec <= 86400:
        await message.answer("Интервал — от 10 секунд до суток (86400)")
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
    start = _parse_hhmm(parts[1])
    end = _parse_hhmm(parts[2])
    if start is None or end is None:
        await message.answer("Формат времени: HH:MM")
        return
    if start == end:
        # Иначе админ видит «Ночная пауза: 23:00–23:00» и думает, что
        # она включена, а _in_night честно возвращает False.
        await message.answer("Начало и конец не могут совпадать")
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
    # Опечатка (/setgroup ДП-2б -> ДП-2Б) раньше сохранялась молча, и
    # поллер каждый день слал в чат «пар нет». Проверяем, что группа есть.
    known = await repo.base_lessons.get_groups()
    if group not in known and f"{group}@vuz" in known:
        # Группы вуза хранятся с суффиксом — не заставляем админа его помнить.
        group = f"{group}@vuz"
    if known and group not in known:
        near = [g for g in known if g.startswith(group[:4])][:8]
        hint = f"\n\nПохожие: {', '.join(near)}" if near else ""
        await message.answer(f"Группы <b>{group}</b> нет в расписании.{hint}")
        return
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


async def _send_preview(message: Message, repo: RequestsRepo, config: Config, date, group: str, send_image: bool = True):
    bell, lunches = await repo.bell_schedule.get_context()
    lessons = await repo.college_lessons.get_for_group_date(group, date)
    text = format_day(date, lessons, bell, lunches, "brief")
    photo = photos.random_photo(config.photos_path, photos.weekday_folder(date)) if send_image else None
    if photo:
        await message.bot.send_photo(message.chat.id, FSInputFile(photo), caption=text)
    else:
        await message.answer(text)


async def _preview_for_user(message: Message, repo: RequestsRepo, config: Config, date, user):
    bell, lunches = await repo.bell_schedule.get_context()
    is_teacher = user.role == "teacher"
    if is_teacher:
        if not user.teacher_name:
            await message.answer("У тебя не выбрана фамилия")
            return
        lessons = await repo.college_lessons.get_for_teacher_date(user.teacher_name, date)
        gcg = await repo.users.get_group_course_map() or None
    else:
        if not user.group:
            # Раньше сообщение было тупиком: ни кнопок, ни подсказки,
            # что делать дальше.
            await message.answer(
                "У тебя не выбрана группа — без неё нечего показать.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🎯 Выбрать группу",
                                          callback_data="pick")],
                    [InlineKeyboardButton(text="⚙️ Настройки",
                                          callback_data="settings")]]))
            return
        lessons = await repo.college_lessons.get_for_group_date(user.group, date)
        cg = bells_group(user.group, user.course)
        gcg = {user.group: cg} if cg else None
    text = format_day(date, lessons, bell, lunches, "brief",
                      meta="group" if is_teacher else "teacher",
                      show_rov=not is_teacher,
                      group_course_group=gcg)
    photo = photos.random_photo(config.photos_path, photos.weekday_folder(date)) if (user.send_image and not is_teacher) else None
    if photo:
        await message.bot.send_photo(message.chat.id, FSInputFile(photo), caption=text)
    else:
        await message.answer(text)


async def _report_broadcast(bot, chat_id, items, rate):
    sent = await broadcast_many(bot, items, rate=rate)
    try:
        await bot.send_message(chat_id, f"Готово: отправлено {sent}/{len(items)}")
    except Exception:
        pass


async def _confirm_broadcast(message: Message, repo: RequestsRepo, state: FSMContext, text: str, users=None, label: str = "пользователям"):
    if users is None:
        users = await repo.users.get_all()
    # Нечего отправлять — говорим прямо и не показываем кнопку. Иначе
    # админ видит «Отправить 0 пользователям» и всё равно жмёт.
    if not users:
        await message.answer(f"В выбранной аудитории ({label}) никого нет — "
                             f"рассылать некому.")
        await state.clear()
        return
    await state.update_data(broadcast_text=text, broadcast_ids=[u.id for u in users])
    await state.set_state(AdminState.confirm_broadcast)
    preview = text if len(text) <= 400 else text[:400] + "…"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Отправить", callback_data="adm:bc_send"),
         InlineKeyboardButton(text="❌ Отмена", callback_data="adm:bc_cancel")],
    ])
    await message.answer(f"Отправить <b>{len(users)}</b> {label}?\n\n{preview}", reply_markup=kb)


async def _target_users(repo: RequestsRepo, target: str):
    """Кому слать ручную рассылку — только подписавшимся.

    Раньше брались get_all/get_by_group/get_teachers_users, и ни один не
    смотрел на subscribed: одиннадцать человек получали каждую рассылку,
    хотя нажали «Отключить уведомления». Автоматические уведомления о
    расписании фильтруют правильно, а ручные — нет. Человек разницы не
    видит: отписался, а сообщения идут.
    """
    if target == "teachers":
        return await repo.users.get_teachers_users(), "преподавателям"
    if target == "all" or not target:
        return await repo.users.get_subscribed(), "пользователям"
    return await repo.users.get_subscribed_by_group(target), f"в группе {target}"


def _broadcast_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Всем", callback_data="adm:broadcast")],
        [InlineKeyboardButton(text="👨‍🏫 Преподавателям", callback_data="adm:broadcast_teachers")],
        [InlineKeyboardButton(text="🎓 Группе", callback_data="adm:broadcast_group")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="adm:back")],
    ])


@admin_router.message(Command("broadcast"))
async def broadcast_cmd(message: Message, repo: RequestsRepo, config: Config, state: FSMContext):
    if not _is_admin(message, config):
        return
    parts = message.text.split(None, 1)
    if len(parts) < 2:
        await state.set_state(AdminState.set_broadcast)
        await message.answer("Введи текст сообщения для всех:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="adm:bc_cancel")]]))
        return
    await _confirm_broadcast(message, repo, state, parts[1])


@admin_router.message(Command("broadcast_teachers"))
async def broadcast_teachers_cmd(message: Message, repo: RequestsRepo, config: Config, state: FSMContext):
    if not _is_admin(message, config):
        return
    parts = message.text.split(None, 1)
    if len(parts) < 2:
        await message.answer("Формат: /broadcast_teachers текст")
        return
    teachers = await repo.users.get_teachers_users()
    if not teachers:
        await message.answer("Преподавателей пока нет")
        return
    await _confirm_broadcast(message, repo, state, parts[1], teachers, label="преподавателям")


@admin_router.message(Command("broadcast_group"))
async def broadcast_group_cmd(message: Message, repo: RequestsRepo, config: Config, state: FSMContext):
    if not _is_admin(message, config):
        return
    parts = message.text.split(None, 2)
    if len(parts) < 3:
        await message.answer("Формат: /broadcast_group ДП-26 текст")
        return
    group = parts[1].upper()
    users = await repo.users.get_by_group(group)
    if not users:
        await message.answer(f"В группе {group} никого нет")
        return
    await _confirm_broadcast(message, repo, state, parts[2], users, label=f"в группе {group}")


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
            await _preview_for_user(message, repo, config, latest, user)
        else:
            await _send_preview(message, repo, config, latest, arg.upper(), send_image=user.send_image)
        return
    await message.answer("🔔 <b>Тест уведомления</b>\n\nКому отправить?", reply_markup=_notify_menu_kb())


@admin_router.callback_query(lambda cb: cb.data == "adm:broadcast_menu")
async def cb_broadcast_menu(cb: CallbackQuery, config: Config):
    if not _is_admin_cb(cb, config):
        return
    await cb.message.edit_text("📢 <b>Рассылка</b>\n\nКому отправить?", reply_markup=_broadcast_menu_kb())
    await cb.answer()


@admin_router.callback_query(lambda cb: cb.data == "adm:broadcast")
async def cb_broadcast(cb: CallbackQuery, config: Config, state: FSMContext):
    if not _is_admin_cb(cb, config):
        return
    await state.update_data(broadcast_target="all")
    await state.set_state(AdminState.set_broadcast)
    await cb.message.answer("Введи текст сообщения для всех:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="adm:bc_cancel")]]))
    await cb.answer()


@admin_router.callback_query(lambda cb: cb.data == "adm:broadcast_teachers")
async def cb_broadcast_teachers(cb: CallbackQuery, config: Config, state: FSMContext):
    if not _is_admin_cb(cb, config):
        return
    await state.update_data(broadcast_target="teachers")
    await state.set_state(AdminState.set_broadcast)
    await cb.message.answer("Введи текст сообщения для преподавателей:")
    await cb.answer()


@admin_router.callback_query(lambda cb: cb.data == "adm:broadcast_group")
async def cb_broadcast_group(cb: CallbackQuery, config: Config, state: FSMContext):
    if not _is_admin_cb(cb, config):
        return
    await state.set_state(AdminState.set_group_broadcast)
    await cb.message.answer("Напиши номер группы (например, ДП-26):", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="adm:bc_cancel")]]))
    await cb.answer()


@admin_router.message(AdminState.set_group_broadcast)
async def m_group_broadcast(message: Message, repo: RequestsRepo, state: FSMContext):
    group = message.text.strip().upper()
    # Та же проверка, что в /broadcast_group. Без неё опечатка («МУСОР»)
    # принималась за чистую монету: админ вводил текст и видел
    # «Отправить 0 пользователям» вместо «такой группы нет».
    users = await repo.users.get_by_group(group)
    if not users:
        await message.answer(f"В группе {group} никого нет. Проверь номер.")
        return
    await state.update_data(broadcast_target=group)
    await state.set_state(AdminState.set_broadcast)
    await message.answer(f"Введи текст сообщения для группы {group}:")


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
    _spawn(notify_new_schedule(cb.message.bot, session_pool, [(latest, True, set())],
                               rate, config.photos_path))


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
    await cb.answer()
    await _preview_for_user(cb.message, repo, config, latest, user)


@admin_router.message(AdminState.set_broadcast)
async def m_broadcast(message: Message, repo: RequestsRepo, state: FSMContext):
    data = await state.get_data()
    target = data.get("broadcast_target", "all")
    users, label = await _target_users(repo, target)
    await _confirm_broadcast(message, repo, state, message.text.strip(), users, label)


@admin_router.callback_query(lambda cb: cb.data == "adm:bc_send")
async def cb_bc_send(cb: CallbackQuery, repo: RequestsRepo, config: Config, state: FSMContext):
    if not _is_admin_cb(cb, config):
        return
    data = await state.get_data()
    text = data.get("broadcast_text")
    ids = data.get("broadcast_ids")
    await state.clear()
    if not text:
        await cb.answer("Нет текста")
        return
    # Пустой список — это «в выбранной аудитории никого», а не «всем».
    # Раньше [] был falsy и уводил рассылку на всех 227 человек, хотя
    # подтверждение показывало «Отправить 0 пользователям». Отозвать
    # такое сообщение нельзя. None остаётся «списка нет — всем».
    if ids is None:
        ids = [u.id for u in await repo.users.get_all()]
    items = [(uid, text) for uid in ids]
    rate = float((await repo.settings.get_all())["notify_rate"])
    await cb.message.edit_text(f"Рассылка запущена ({len(items)} получателей)")
    await cb.answer()
    _spawn(_report_broadcast(cb.message.bot, cb.message.chat.id, items, rate))


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
            "Пример: /setbell MONDAY I_IV 1 09:25-10:10\n\n"
            "С перерывом внутри пары — четыре времени:\n"
            "/setbell OTHER I_IV 2 10:45-11:30-11:55-12:40\n"
            "(начало-конец 1-го часа-начало 2-го-конец пары)"
        )
        return

    day_type, course_group, para_s, time_s = parts[1].upper(), parts[2].upper(), parts[3], parts[4]

    if day_type not in VALID_DAY or course_group not in VALID_COURSE:
        await message.answer("DAY_TYPE: MONDAY|OTHER, COURSE_GROUP: ALL|I_IV|II_III|VUZ")
        return

    try:
        para = int(para_s)
        times = time_s.split("-")
        if len(times) == 2:
            start, end = (datetime.time.fromisoformat(t) for t in times)
            h1_end = h2_start = None
        elif len(times) == 4:
            start, h1_end, h2_start, end = (
                datetime.time.fromisoformat(t) for t in times)
        else:
            raise ValueError("ожидалось 2 или 4 времени")
    except ValueError:
        await message.answer(
            "Неверный формат. Пример: /setbell MONDAY I_IV 1 09:25-10:10\n"
            "С перерывом: /setbell OTHER I_IV 2 10:45-11:30-11:55-12:40")
        return

    # Дальше проверки смысла: формат верный, а звонок бессмысленный.
    # 8 — потому что у вуза 8 пар (_format_bell_vuz), у колледжа 6.
    if not 1 <= para <= 8:
        await message.answer(
            "Номер пары — от 1 до 8.\n"
            "0 зарезервирован под «Разговоры о важном», его так не задать.")
        return
    # Пара, кончающаяся раньше начала, ломает напоминания: bell.py
    # вешает «Конец пары» на end, то есть раньше start.
    if start >= end:
        await message.answer(
            f"Конец ({end:%H:%M}) должен быть позже начала ({start:%H:%M}).")
        return
    # Перерыв должен лежать внутри пары, иначе экран нарисует
    # «11:55–11:30» и напоминания встанут не по порядку.
    if h1_end and h2_start and not start < h1_end <= h2_start < end:
        await message.answer(
            f"Перерыв должен идти по порядку: {start:%H:%M} < "
            f"конец 1-го часа ≤ начало 2-го < {end:%H:%M}.")
        return
    # ALL — это не «все курсы», а слот «Разговоров о важном» (para=0).
    # С para != 0 такая строка не отрисуется никогда.
    if course_group == "ALL" and para != 0:
        await message.answer(
            "COURSE_GROUP=ALL бывает только у «Разговоров о важном» (para=0).\n"
            "Для пар используй I_IV или II_III.")
        return

    await repo.bell_schedule.upsert(day_type, course_group, para, start, end,
                                    h1_end=h1_end, h2_start=h2_start)
    if h1_end and h2_start:
        when = f"{start:%H:%M}–{h1_end:%H:%M} / {h2_start:%H:%M}–{end:%H:%M}"
    else:
        when = f"{start:%H:%M}–{end:%H:%M}"
    await message.answer(f"Сохранено: {day_type} {course_group} п{para} {when}")


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


@admin_router.callback_query(lambda cb: cb.data in ("adm:stats:college", "adm:stats:vuz"))
async def cb_adm_stats_unit(cb: CallbackQuery, repo: RequestsRepo, config: Config):
    if not _is_admin_cb(cb, config):
        return
    unit = cb.data.rsplit(":", 1)[1]
    text, kb = await _build_stats_unit(repo, unit)
    await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer()


@admin_router.callback_query(lambda cb: cb.data == "adm:stats:groups")
async def cb_adm_stats_groups(cb: CallbackQuery, repo: RequestsRepo, config: Config):
    if not _is_admin_cb(cb, config):
        return
    text, kb = await _build_stats_groups(repo)
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


def _user_marks(u) -> str:
    marks = []
    if u.subscribed:
        marks.append("🔔")
    if u.send_image:
        marks.append("🐱")
    if u.last_seen and u.last_seen.date() == datetime.date.today():
        marks.append("⚡")
    if u.bell_mode and u.bell_mode != "off":
        marks.append("⏰")
    return (" " + "".join(marks)) if marks else ""


def _user_line(u) -> str:
    tag = f"@{u.username}" if u.username else str(u.id)
    return f"{tag} — {u.full_name}{_user_marks(u)}"


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

    lines = [f"👥 <b>{title}</b> ({len(users)})", "🔔 рассылка · 🐱 фото · ⚡ был сегодня · ⏰ звонки\n"]
    for u in users:
        lines.append(_user_line(u))
    if not users:
        lines.append("Никого нет")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад к статистике", callback_data="adm:stats")],
    ])
    await cb.message.edit_text("\n".join(lines), reply_markup=kb)
    await cb.answer()


async def _teachers_text(repo: RequestsRepo) -> str:
    teachers = await repo.users.get_teachers_users()
    lines = [f"👨‍🏫 <b>Преподаватели</b> ({len(teachers)})\n"]
    for t in sorted(teachers, key=lambda x: (x.teacher_name or "")):
        tag = f"@{t.username}" if t.username else str(t.id)
        line = f"{tag} — {t.teacher_name}{_user_marks(t)}"
        lines.append(line)
    if not teachers:
        lines.append("Пока нет")
    return "\n".join(lines)


@admin_router.message(Command("teachers"))
async def teachers_cmd(message: Message, repo: RequestsRepo, config: Config):
    if not _is_admin(message, config):
        return
    await message.answer(await _teachers_text(repo))


@admin_router.callback_query(lambda cb: cb.data == "adm:teachers")
async def cb_adm_teachers(cb: CallbackQuery, repo: RequestsRepo, config: Config):
    if not _is_admin_cb(cb, config):
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад к статистике", callback_data="adm:stats")],
    ])
    await cb.message.edit_text(await _teachers_text(repo), reply_markup=kb)
    await cb.answer()


@admin_router.my_chat_member()
async def on_bot_left_chat(event, repo: RequestsRepo):
    """Бота выгнали из группы — убрать запись сразу.

    Кнопка отвязки есть, но админ может не заметить выгон, а рассылка
    каждый раз пыталась бы туда писать и логировала ошибку. Ограничение
    (``restricted``) не повод удалять: бот в чате остаётся.
    """
    status = getattr(event.new_chat_member, "status", None)
    if status in ("left", "kicked"):
        await repo.chats.remove(event.chat.id)
        logging.info("чат %s: бота выгнали, отвязано", event.chat.id)


@admin_router.callback_query(lambda cb: cb.data == "adm:chats")
async def cb_adm_chats(cb: CallbackQuery, repo: RequestsRepo, config: Config):
    if not _is_admin_cb(cb, config):
        return
    await cb.message.edit_text(await _chats_text(repo),
                               reply_markup=await _chats_kb(repo))
    await cb.answer()


async def _chats_text(repo: RequestsRepo) -> str:
    chats = await repo.chats.get_all()
    if not chats:
        return "💬 <b>Чаты</b>\n\nПока нет"
    lines = ["💬 <b>Чаты</b>\n"]
    for c in chats:
        lines.append(f"{c.id} · {c.title or '—'} → {c.group or '—'}")
    return "\n".join(lines)


async def _chats_kb(repo: RequestsRepo) -> InlineKeyboardMarkup:
    """Список чатов с кнопкой отвязки у каждого.

    Без неё запись висела вечно: бота выгнали из группы, а рассылка
    каждый раз пыталась туда писать и логировала TelegramForbiddenError.
    """
    rows = [[InlineKeyboardButton(text=f"✖️ Отвязать {c.title or c.id}",
                                  callback_data=f"adm:unchat:{c.id}")]
            for c in await repo.chats.get_all()]
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="adm:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@admin_router.callback_query(lambda cb: cb.data.startswith("adm:unchat:"))
async def cb_adm_unchat(cb: CallbackQuery, repo: RequestsRepo, config: Config):
    if not _is_admin_cb(cb, config):
        return
    chat_id = int(cb.data.rsplit(":", 1)[1])
    await repo.chats.remove(chat_id)
    logging.info("чат %s отвязан админом", chat_id)
    await cb.message.edit_text(await _chats_text(repo),
                               reply_markup=await _chats_kb(repo))
    await cb.answer("Отвязано")


# ---- настройки: ввод значением ----
# Одна таблица вместо двенадцати обработчиков: для каждой настройки
# отличается только вопрос, валидатор и текст подтверждения.

@dataclass(frozen=True)
class _Setting:
    state: State
    prompt: str
    keys: tuple[str, ...]            # один или два ключа в setting
    parse: Callable[[str], tuple[str, ...]]   # сырой ввод -> значения
    ok: str                          # шаблон подтверждения


def _num(text: str, lo: int, hi: int) -> tuple[str, ...]:
    value = int(text)
    if not lo <= value <= hi:
        raise ValueError
    return (str(value),)


def _rate(text: str) -> tuple[str, ...]:
    value = float(text)
    if not 0 < value <= 30:
        raise ValueError
    return (str(value),)


def _night(text: str) -> tuple[str, ...]:
    parts = text.split()
    if len(parts) != 2:
        raise ValueError
    # Через _parse_hhmm, а не fromisoformat: «23:00+03:00» даёт
    # aware-время, и поллер молча перестаёт опрашивать сайт.
    if _parse_hhmm(parts[0]) is None or _parse_hhmm(parts[1]) is None:
        raise ValueError
    return (parts[0], parts[1])


def _url(text: str) -> tuple[str, ...]:
    """Ссылка поддержки: http(s) или tg, либо пусто (убрать кнопку).

    Telegram принимает в url кнопки только эти схемы и на остальное
    отвечает BUTTON_URL_INVALID, отклоняя сообщение целиком. А меню —
    это 9 обработчиков, и глобального обработчика ошибок нет: студент
    не получил бы ничего, а админ не смог бы исправить — «Настройки»
    живут в том же меню, отдельной команды нет.

    Одного префикса мало: «https://» без хоста Telegram тоже отбивает.
    """
    value = text.strip()
    if not value:
        return ("",)
    for scheme in ("https://", "http://", "tg://"):
        if value.startswith(scheme) and value[len(scheme):].strip():
            return (value,)
    raise ValueError


SETTINGS: dict[str, _Setting] = {
    "poll": _Setting(AdminState.set_poll, "Введи интервал опроса (секунд, мин. 10):",
                     ("poll_interval",), lambda t: _num(t, 10, 86_400),
                     "Интервал опроса: {} сек"),
    "rate": _Setting(AdminState.set_rate, "Введи скорость рассылки (сообщений/сек, 0–30):",
                     ("notify_rate",), _rate,
                     "Скорость рассылки: {} сообщ/сек"),
    "night": _Setting(AdminState.set_night, "Введи ночное окно «HH:MM HH:MM»:",
                      ("night_start", "night_end"), _night, "Ночная пауза: {}–{}"),
    "support": _Setting(AdminState.set_support, "Отправь ссылку на группу поддержки:",
                        ("support_link",), _url, "Ссылка поддержки: {}"),
}


@admin_router.callback_query(F.data == "adm:set_cancel")
async def cb_set_cancel(cb: CallbackQuery, config: Config, state: FSMContext):
    if not _is_admin_cb(cb, config):
        return
    await state.clear()
    await cb.message.edit_text("Отменено", reply_markup=InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад",
                                               callback_data="adm:settings")]]))
    await cb.answer()


@admin_router.callback_query(F.data.startswith("adm:set:"))
async def cb_setting(cb: CallbackQuery, config: Config, state: FSMContext):
    if not _is_admin_cb(cb, config):
        return
    item = SETTINGS.get(cb.data.split(":")[-1])
    if not item:
        await cb.answer("Неизвестная настройка", show_alert=True)
        return
    await state.set_state(item.state)
    # Без кнопки отмены из ввода не было выхода: state висел, пока не
    # пришлёшь валидное значение, и любое сообщение уходило в парсер.
    await cb.message.answer(item.prompt, reply_markup=InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена",
                                               callback_data="adm:set_cancel")]]))
    await cb.answer()


@admin_router.message(*[s.state for s in SETTINGS.values()])
async def m_setting(message: Message, repo: RequestsRepo, state: FSMContext):
    current = await state.get_state()
    item = next((s for s in SETTINGS.values() if s.state.state == current), None)
    if item is None:
        await state.clear()
        return
    try:
        value = item.parse(message.text.strip())
    except (ValueError, TypeError):
        # Состояние НЕ трогаем: «Попробуй ещё раз» иначе уходил бы в
        # any_text, и следующее верное значение не попадало бы в m_setting.
        await message.answer("Неверное значение. Попробуй ещё раз.")
        return
    await state.clear()
    for key, val in zip(item.keys, value):
        await repo.settings.set(key, val)
    await message.answer(item.ok.format(*value))


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


# --- Редакторы расписания (старосты) --------------------------------------

def _editors_kb(editors, users_by_id: dict) -> InlineKeyboardMarkup:
    rows = []
    for e in editors:
        u = users_by_id.get(e.user_id)
        name = _user_option(u) if u else str(e.user_id)
        rows.append([InlineKeyboardButton(
            text=f"❌ {name} → {e.group}", callback_data=f"adm:ed_del:{e.user_id}")])
    rows.append([InlineKeyboardButton(text="➕ Добавить редактора",
                                      callback_data="adm:ed_add")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="adm:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _editors_text(repo: RequestsRepo) -> str:
    editors = await repo.editors.get_all()
    lines = ["✏️ <b>Редакторы расписания</b>\n"]
    if not editors:
        lines.append("<i>Пока никого. Редактор может править только свою группу.</i>")
    else:
        lines.append(f"Всего: <b>{len(editors)}</b>")
        lines.append("")
        lines.append("Чтобы <b>отозвать</b> право — нажми на строку.")
    return "\n".join(lines)


@admin_router.callback_query(lambda cb: cb.data == "adm:editors")
async def cb_editors(cb: CallbackQuery, repo: RequestsRepo, config: Config):
    if not _is_admin_cb(cb, config):
        return
    editors = await repo.editors.get_all()
    users = await repo.users.get_all()
    users_by_id = {u.id: u for u in users}
    await cb.message.edit_text(await _editors_text(repo),
                               reply_markup=_editors_kb(editors, users_by_id))
    await cb.answer()


@admin_router.callback_query(lambda cb: cb.data.startswith("adm:ed_del:"))
async def cb_editor_revoke(cb: CallbackQuery, repo: RequestsRepo, config: Config):
    if not _is_admin_cb(cb, config):
        return
    user_id = int(cb.data.split(":")[2])
    group = await repo.editors.get_group_for(user_id)
    await repo.editors.revoke(user_id)
    editors = await repo.editors.get_all()
    users = await repo.users.get_all()
    users_by_id = {u.id: u for u in users}
    await cb.message.edit_text(
        f"Право редактора отозвано (группа {group}).\n\n" + await _editors_text(repo),
        reply_markup=_editors_kb(editors, users_by_id))
    await cb.answer("Отозвано")


def _user_option(u) -> str:
    """«@ник — Имя (ГРУППА)» — понятная подпись для кнопки."""
    parts = []
    if u.username:
        parts.append(f"@{u.username}")
    name = (u.full_name or "").strip()
    if name and name.lower() != (u.username or "").lower():
        parts.append(name[:22])
    label = " — ".join(parts) or str(u.id)
    if u.group:
        label += f" ({u.group})"
    return label


def _pick_editor_kb(found, query: str) -> InlineKeyboardMarkup:
    rows = []
    for u in found:
        rows.append([InlineKeyboardButton(
            text=_user_option(u)[:60], callback_data=f"adm:ed_pick:{u.id}")])
    rows.append([InlineKeyboardButton(text="🔍 Искать ещё",
                                      callback_data="adm:ed_add")])
    rows.append([InlineKeyboardButton(text="⬅️ Отмена", callback_data="adm:editors")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@admin_router.callback_query(lambda cb: cb.data == "adm:ed_add")
async def cb_editor_add(cb: CallbackQuery, repo: RequestsRepo, config: Config,
                        state: FSMContext):
    if not _is_admin_cb(cb, config):
        return
    await state.set_state(AdminState.set_editor)
    await cb.message.edit_text(
        "✏️ <b>Новый редактор</b>\n\n"
        "Пришли <b>@никнейм</b> того, кому даёшь права.\n\n"
        "Например: <code>@virp0m</code> или <code>virp0m</code>\n\n"
        "Можно также ввести <b>имя</b> или <b>id</b> — я поищу.\n"
        "<i>Если никто не нашёлся — попроси старосту открыть бота "
        "и нажать «Старт».</i>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Отмена", callback_data="adm:editors")]]))
    await cb.answer()


@admin_router.message(AdminState.set_editor)
async def set_editor(message: Message, repo: RequestsRepo, config: Config,
                     state: FSMContext):
    if not _is_admin(message, config):
        return
    query = (message.text or "").strip()
    if not query:
        await message.answer("Пришли @никнейм, имя или id.")
        return

    found = await repo.users.search(query, limit=8)
    if not found:
        await message.answer(
            f"🔍 По запросу <code>{query}</code> никто не найден.\n\n"
            "Проверь написание или попроси человека нажать «Старт» в боте.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔍 Искать ещё", callback_data="adm:ed_add")],
                [InlineKeyboardButton(text="⬅️ Отмена", callback_data="adm:editors")]]))
        return

    if len(found) == 1:
        await _ask_group(message, repo, state, found[0])
        return

    await message.answer(
        f"🔍 Нашёл <b>{len(found)}</b> — выбери нужного 👇",
        reply_markup=_pick_editor_kb(found, query))
    await state.update_data(candidates=[u.id for u in found])


async def _ask_group(event, repo: RequestsRepo, state: FSMContext, user):
    """Спросить группу кнопками из известных групп."""
    # Группы из обоих источников: из пар с сайта и из базового расписания.
    # Вузовские отбрасываем: из 129 групп 92 — это @vuz (71%), и админ
    # ошибался на первом же неверном нажатии. Редактор вузовскую группу
    # открывает и показывает пары, но правка на ней не применяется —
    # base_lesson для неё перезапишется синком при следующем опросе.
    base_groups = await repo.base_lessons.get_groups()
    site_groups = await repo.college_lessons.get_groups()
    groups = sorted(g for g in set(base_groups) | set(site_groups) if not is_vuz(g))
    rows = []
    for i in range(0, len(groups), 3):
        rows.append([InlineKeyboardButton(text=g, callback_data=f"adm:ed_grp:{g}")
                     for g in groups[i:i + 3]])
    rows.append([InlineKeyboardButton(text="⬅️ Отмена", callback_data="adm:editors")])
    await state.update_data(editor_user_id=user.id)
    text = (f"👤 <b>{_user_option(user)}</b>\n\n"
            "На какую группу дать права? 👇")
    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    if isinstance(event, CallbackQuery):
        await event.message.edit_text(text, reply_markup=kb)
    else:
        await event.answer(text, reply_markup=kb)


@admin_router.callback_query(lambda cb: cb.data.startswith("adm:ed_pick:"))
async def cb_editor_pick(cb: CallbackQuery, repo: RequestsRepo, config: Config,
                         state: FSMContext):
    if not _is_admin_cb(cb, config):
        return
    user_id = int(cb.data.split(":")[2])
    user = await repo.users.get(user_id)
    if not user:
        await cb.answer("Пользователь не найден", show_alert=True)
        return
    await _ask_group(cb, repo, state, user)
    await cb.answer()


@admin_router.callback_query(lambda cb: cb.data.startswith("adm:ed_grp:"))
async def cb_editor_group(cb: CallbackQuery, repo: RequestsRepo, config: Config,
                          state: FSMContext):
    if not _is_admin_cb(cb, config):
        return
    group = cb.data.split(":", 2)[2]
    data = await state.get_data()
    user_id = data.get("editor_user_id")
    if not user_id:
        await cb.answer("Начни заново", show_alert=True)
        return

    user = await repo.users.get(user_id)
    await repo.editors.grant(user_id, group, granted_by=cb.from_user.id)
    await state.clear()

    editors = await repo.editors.get_all()
    users = await repo.users.get_all()
    users_by_id = {u.id: u for u in users}
    who = _user_option(user) if user else str(user_id)
    await cb.message.edit_text(
        f"✅ <b>{who}</b> теперь может править расписание группы <b>{group}</b>.\n\n"
        + await _editors_text(repo),
        reply_markup=_editors_kb(editors, users_by_id))
    await cb.answer("Права выданы")

    # уведомим нового редактора, чтобы он знал, что делать
    try:
        from tgbot.services.broadcaster import send_message
        await send_message(
            cb.bot, user_id,
            f"✏️ Тебе дали права редактора расписания группы <b>{group}</b>.\n\n"
            "Открой /start — в меню появится «✏️ Редактор расписания».")
    except Exception:
        logging.exception("не удалось уведомить нового редактора")
