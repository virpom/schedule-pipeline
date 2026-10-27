"""Редактор расписания для старост.

Принципы:
  * староста правит ТОЛЬКО свою группу;
  * базовое расписание — по чётности недели, замены — по дате;
  * ввод кнопками: дата, пара, чётность и преподаватель выбираются,
    время никогда не вводится вручную (берётся из расписания звонков);
  * перед сохранением показывается предпросмотр «как увидят студенты»;
  * все правки пишутся в журнал, последнюю можно откатить.
"""
import datetime
import json
import logging
from html import escape

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from common.schedule import (
    MAX_PARA,
    max_para,
    PARITY_ANY,
    PARITY_EVEN,
    PARITY_LABELS,
    PARITY_ODD,
    SUB_ADD,
    SUB_CANCEL,
    SUB_REPLACE,
    WEEKDAY_FULL,
    bells_group,
    week_parity,
)
from infrastructure.database.models import User
from infrastructure.database.repo.requests import RequestsRepo
from tgbot.services.notify_edits import notify_group_about_edit
from tgbot.services.schedule_layer import PARITY_OFFSET, Slot, get_day_slots

editor_router = Router()

WEEKDAY_SHORT = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

EDITOR_TITLE = "✏️ <b>Редактор расписания</b>"


class EditorState(StatesGroup):
    subject = State()
    teacher = State()
    room = State()


# --- доступ ---------------------------------------------------------------

async def editor_group(repo: RequestsRepo, user_id: int) -> str | None:
    """Группа, которую пользователь вправе править (или None)."""
    return await repo.editors.get_group_for(user_id)


def _no_rights_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu")],
    ])


# --- клавиатуры -----------------------------------------------------------

def editor_main_kb(group: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Правки на дату (замены)",
                              callback_data="ed:subs")],
        [InlineKeyboardButton(text="🗓 Базовое расписание",
                              callback_data="ed:base")],
        [InlineKeyboardButton(text="📜 Журнал правок", callback_data="ed:log")],
        [InlineKeyboardButton(text="👁 Как видят студенты",
                              callback_data="ed:preview")],
        [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu")],
    ])


def base_kb(group: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Пн", callback_data="ed:bday:1"),
         InlineKeyboardButton(text="Вт", callback_data="ed:bday:2"),
         InlineKeyboardButton(text="Ср", callback_data="ed:bday:3")],
        [InlineKeyboardButton(text="Чт", callback_data="ed:bday:4"),
         InlineKeyboardButton(text="Пт", callback_data="ed:bday:5"),
         InlineKeyboardButton(text="Сб", callback_data="ed:bday:6")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="ed:back")],
    ])


def parity_kb(weekday: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔵 Чётная неделя",
                              callback_data=f"ed:bp:{weekday}:{PARITY_EVEN}")],
        [InlineKeyboardButton(text="🔴 Нечётная неделя",
                              callback_data=f"ed:bp:{weekday}:{PARITY_ODD}")],
        [InlineKeyboardButton(text="⚪️ Каждую неделю",
                              callback_data=f"ed:bp:{weekday}:{PARITY_ANY}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="ed:base")],
    ])


def paras_kb(weekday: int, parity: str, slots: list[Slot], prefix: str = "ed:bs",
             last: int = MAX_PARA) -> InlineKeyboardMarkup:
    """Список пар дня с текущим содержимым.

    ``last`` — сколько слотов показать: 6 у колледжа, 8 у вуза.
    """
    by_para = {s.para: s for s in slots}
    rows = []
    for p in range(1, last + 1):
        slot = by_para.get(p)
        label = f"{p}) {slot.subject[:24]}" if slot else f"{p}) — пусто"
        if slot and slot.changed:
            label += " 🔄"
        rows.append([InlineKeyboardButton(
            text=label, callback_data=f"{prefix}:{weekday}:{parity}:{p}")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="ed:base")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def slot_actions_kb(weekday: int, parity: str, para: int, has_value: bool,
                    weeks: str = "") -> InlineKeyboardMarkup:
    # weeks едет в callback: без него upsert создаёт дубль, а
    # delete_slot не находит строку. 64 байта хватает — список недель
    # у вуза короткий ("5,6,7,8" / "9,10,11,12,13").
    wk = weeks or "_"
    rows = [[InlineKeyboardButton(
        text="✏️ Изменить", callback_data=f"ed:edit:{weekday}:{parity}:{para}:{wk}")]]
    if has_value:
        rows.append([InlineKeyboardButton(
            text="🗑 Убрать пару", callback_data=f"ed:del:{weekday}:{parity}:{para}:{wk}")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад",
                                      callback_data=f"ed:bpar:{weekday}:{parity}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def sub_dates_kb(group: str, today: datetime.date) -> InlineKeyboardMarkup:
    """Даты для замен: вчера .. +6 дней (замены дают на день вперёд)."""
    rows = []
    for delta in range(-1, 7):
        d = today + datetime.timedelta(days=delta)
        label = f"{WEEKDAY_SHORT[d.weekday()]} {d.strftime('%d.%m')}"
        if delta == -1:
            label += " (вчера)"
        elif delta == 0:
            label += " (сегодня)"
        elif delta == 1:
            label += " (завтра)"
        parity = "🔵" if week_parity(d, PARITY_OFFSET) == PARITY_EVEN else "🔴"
        rows.append([InlineKeyboardButton(
            text=f"{parity} {label}", callback_data=f"ed:sd:{d.isoformat()}")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="ed:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def sub_slots_kb(date_iso: str, slots: list[Slot], subs_by_para: dict,
                 last: int = MAX_PARA) -> InlineKeyboardMarkup:
    by_para = {s.para: s for s in slots}
    rows = []
    for p in range(1, last + 1):
        sub = subs_by_para.get(p)
        slot = by_para.get(p)
        if sub and sub.action == SUB_CANCEL:
            label = f"{p}) ❌ отменена"
        elif sub:
            label = f"{p}) 🔄 {sub.subject[:20]}"
        elif slot:
            label = f"{p}) {slot.subject[:24]}"
        else:
            label = f"{p}) — пусто"
        rows.append([InlineKeyboardButton(
            text=label, callback_data=f"ed:ss:{date_iso}:{p}")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="ed:subs")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def sub_actions_kb(date_iso: str, para: int, has_sub: bool, base_slot: Slot | None) -> InlineKeyboardMarkup:
    rows = []
    if base_slot or has_sub:
        rows.append([InlineKeyboardButton(
            text="🔄 Заменить", callback_data=f"ed:sedit:{date_iso}:{para}")])
    rows.append([InlineKeyboardButton(
        text="➕ Добавить пару", callback_data=f"ed:sadd:{date_iso}:{para}")])
    if has_sub:
        rows.append([InlineKeyboardButton(
            text="❌ Отменить пару", callback_data=f"ed:scancel:{date_iso}:{para}")])
        rows.append([InlineKeyboardButton(
            text="↩️ Снять замену", callback_data=f"ed:sreset:{date_iso}:{para}")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад",
                                      callback_data=f"ed:sdl:{date_iso}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def cancel_kb(back: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Отмена", callback_data=back)],
    ])


# --- тексты ---------------------------------------------------------------

def _parity_mark(date: datetime.date) -> str:
    return "🔵 чётная" if week_parity(date, PARITY_OFFSET) == PARITY_EVEN else "🔴 нечётная"


# Поля модели объявлены String(256/128/64..512), но SQLite длину не
# проверяет — в предмет влезало сколько угодно. Тогда экран дня пробивал
# лимит Telegram в 4096 символов и не открывался ни у кого в группе.
# Берём минимум из объявленных длин: subject 256, room 64.
_MAX_FIELD = {"предмет": 256, "преподаватель": 128, "кабинет": 64}


def _too_long(value: str, what: str) -> str | None:
    limit = _MAX_FIELD[what]
    if len(value) <= limit:
        return None
    return f"Слишком длинный {what} ({len(value)} символов, максимум {limit})."


def base_day_text(group: str, weekday: int, parity: str, slots: list[Slot]) -> str:
    lines = [
        f"{EDITOR_TITLE}",
        "",
        f"🗓 <b>{WEEKDAY_FULL[weekday - 1]}</b> · "
        f"{'🔵 чётная' if parity == PARITY_EVEN else '🔴 нечётная' if parity == PARITY_ODD else '⚪️ любая'} неделя",
        "",
    ]
    if not slots:
        lines.append("<i>Пар нет</i>")
    else:
        for s in slots:
            meta = " · ".join(x for x in (s.teacher, s.room) if x)
            lines.append(f"<b>{s.para})</b> {escape(s.subject)}")
            if meta:
                lines.append(f"      {meta}")
    lines += ["", "Нажми на пару, чтобы изменить 👇"]
    return "\n".join(lines)


def sub_day_text(group: str, date: datetime.date, slots: list[Slot]) -> str:
    lines = [
        f"{EDITOR_TITLE}",
        "",
        f"📅 <b>{WEEKDAY_FULL[date.weekday()]}, {date.day} "
        f"{'января февраля марта апреля мая июня июля августа сентября октября ноября декабря'.split()[date.month - 1]}</b>",
        f"{_parity_mark(date)} неделя",
        "",
    ]
    if not slots:
        lines.append("<i>Пар нет</i>")
    else:
        for s in slots:
            meta = " · ".join(x for x in (s.teacher, s.room) if x)
            flag = " 🔄" if s.changed else ""
            lines.append(f"<b>{s.para})</b> {escape(s.subject)}{flag}")
            if meta:
                lines.append(f"      {meta}")
    lines += ["", "Нажми на пару, чтобы поставить замену 👇"]
    return "\n".join(lines)


def preview_text(group: str, date: datetime.date, slots: list[Slot],
                 bell=None, lunches=None, course_group: str | None = None) -> str:
    """Предпросмотр ровно так, как увидят студенты.

    Раньше экран собирал текст своей рукой и расходился с реальным:
    не было времени пары (студент видит «11:10–12:45», редактор —
    «Обществознание»), другой порядок строк и не было группы. Теперь
    зовём format_day — тот же код, что и в экране дня.
    """
    from common.schedule import format_day

    lessons = [Slot(s.para, s.subject, s.teacher, s.room,
                    changed=s.changed, action=s.action, comment=s.comment,
                    group=group) for s in slots]
    gcg = {group: course_group} if course_group else None
    # meta="teacher": под парой студент видит преподавателя и кабинет,
    # а не свою же группу. Превью — взгляд студента, не преподавателя.
    return format_day(date, lessons, bell or {}, lunches or {},
                      detail="full", meta="teacher", group_course_group=gcg)


# --- вход -----------------------------------------------------------------

@editor_router.message(F.text == "✏️ Редактор")
async def editor_entry(message: Message, repo: RequestsRepo, user: User):
    group = await editor_group(repo, message.from_user.id)
    if not group:
        await message.answer("У тебя нет прав редактора.", reply_markup=_no_rights_kb())
        return
    await message.answer(
        f"{EDITOR_TITLE}\n\nГруппа: <b>{group}</b>\n\nВыбери раздел 👇",
        reply_markup=editor_main_kb(group),
    )


@editor_router.callback_query(F.data == "ed:back")
async def cb_back(cb: CallbackQuery, repo: RequestsRepo, state: FSMContext):
    await state.clear()
    group = await editor_group(repo, cb.from_user.id)
    if not group:
        await cb.answer("Нет прав", show_alert=True)
        return
    await cb.message.edit_text(
        f"{EDITOR_TITLE}\n\nГруппа: <b>{group}</b>\n\nВыбери раздел 👇",
        reply_markup=editor_main_kb(group),
    )
    await cb.answer()


# --- базовое расписание ---------------------------------------------------

@editor_router.callback_query(F.data == "ed:base")
async def cb_base(cb: CallbackQuery, repo: RequestsRepo, state: FSMContext):
    # Состояние-сирота после «Назад» превращало любой текст в
    # название предмета. Чистим на каждом переходе между экранами.
    await state.clear()
    group = await editor_group(repo, cb.from_user.id)
    if not group:
        await cb.answer("Нет прав", show_alert=True)
        return
    await cb.message.edit_text(
        f"{EDITOR_TITLE}\n\n🗓 <b>Базовое расписание</b>\n\n"
        "Это расписание повторяется каждую неделю.\n"
        "Если предмет бывает только по чётным или нечётным неделям — "
        "выбери нужный вариант.\n\nКакой день настраиваем? 👇",
        reply_markup=base_kb(group),
    )
    await cb.answer()


@editor_router.callback_query(F.data.startswith("ed:bday:"))
async def cb_base_day(cb: CallbackQuery, repo: RequestsRepo):
    group = await editor_group(repo, cb.from_user.id)
    if not group:
        await cb.answer("Нет прав", show_alert=True)
        return
    weekday = int(cb.data.split(":")[2])
    await cb.message.edit_text(
        f"{EDITOR_TITLE}\n\n🗓 <b>{WEEKDAY_FULL[weekday - 1]}</b>\n\n"
        "На какой неделе бывают эти пары? 👇",
        reply_markup=parity_kb(weekday),
    )
    await cb.answer()


async def _render_base_slots(cb: CallbackQuery, repo: RequestsRepo, group: str,
                             weekday: int, parity: str):
    lessons = await repo.base_lessons.get_day(group, weekday, parity)
    slots = [Slot(l.para, l.subject, l.teacher, l.room, weeks=l.weeks or "")
             for l in lessons]
    await cb.message.edit_text(
        base_day_text(group, weekday, parity, slots),
        reply_markup=paras_kb(weekday, parity, slots, last=max_para(group)),
    )


@editor_router.callback_query(F.data.startswith("ed:bp:"))
async def cb_base_parity(cb: CallbackQuery, repo: RequestsRepo):
    group = await editor_group(repo, cb.from_user.id)
    if not group:
        await cb.answer("Нет прав", show_alert=True)
        return
    _, _, weekday_s, parity = cb.data.split(":")
    await _render_base_slots(cb, repo, group, int(weekday_s), parity)
    await cb.answer()


@editor_router.callback_query(F.data.startswith("ed:bpar:"))
async def cb_base_para_back(cb: CallbackQuery, repo: RequestsRepo, state: FSMContext):
    # Состояние-сирота после «Назад» превращало любой текст в
    # название предмета. Чистим на каждом переходе между экранами.
    await state.clear()
    group = await editor_group(repo, cb.from_user.id)
    if not group:
        await cb.answer("Нет прав", show_alert=True)
        return
    _, _, weekday_s, parity = cb.data.split(":")
    await _render_base_slots(cb, repo, group, int(weekday_s), parity)
    await cb.answer()


@editor_router.callback_query(F.data.startswith("ed:bs:"))
async def cb_base_slot(cb: CallbackQuery, repo: RequestsRepo):
    group = await editor_group(repo, cb.from_user.id)
    if not group:
        await cb.answer("Нет прав", show_alert=True)
        return
    _, _, weekday_s, parity, para_s = cb.data.split(":")
    weekday, para = int(weekday_s), int(para_s)
    lessons = await repo.base_lessons.get_day(group, weekday, parity)
    here = [Slot(l.para, l.subject, l.teacher, l.room, weeks=l.weeks or "")
            for l in lessons if l.para == para]

    text = (f"{EDITOR_TITLE}\n\n<b>{WEEKDAY_FULL[weekday - 1]}</b>, "
            f"{PARITY_LABELS.get(parity, parity)} неделя, <b>{para} пара</b>\n\n")
    if not here:
        text += "<i>Пусто</i>"
    elif len(here) == 1:
        slot = here[0]
        text += (f"Сейчас: <b>{slot.subject}</b>\n"
                 f"{' · '.join(x for x in (slot.teacher, slot.room) if x) or '—'}")
        if slot.weeks:
            text += f"\n<i>недели: {slot.weeks}</i>"
    else:
        # У вуза в одном слоте живут несколько дисциплин по разным
        # неделям (на проде 425 таких слотов). Раньше редактор брал
        # первую и правил не ту.
        text += (f"<b>{len(here)} варианта на разных неделях</b> — "
                 f"какой правим?\n")
        for i, slot in enumerate(here):
            text += (f"\n{i + 1}. <b>{slot.subject}</b>"
                     f"\n    недели: {slot.weeks or 'все'}")
            meta = " · ".join(x for x in (slot.teacher, slot.room) if x)
            if meta:
                text += f"\n    {meta}"
    text += "\n\nЧто делаем? 👇"
    if len(here) > 1:
        # Несколько вариантов — сначала выбрать недели, потом действие.
        # Иначе «Изменить» угадала бы, какую строку править.
        kb_rows = [[InlineKeyboardButton(
            text=f"{i + 1}) {(s.subject or '')[:30]}",
            callback_data=f"ed:pick:{weekday}:{parity}:{para}:{i}")]
            for i, s in enumerate(here)]
        kb_rows.append([InlineKeyboardButton(
            text="⬅️ Назад", callback_data=f"ed:bp:{weekday}:{parity}")])
        markup = InlineKeyboardMarkup(inline_keyboard=kb_rows)
    else:
        markup = slot_actions_kb(weekday, parity, para, has_value=bool(here))
    await cb.message.edit_text(text, reply_markup=markup)
    await cb.answer()


@editor_router.callback_query(F.data.startswith("ed:pick:"))
async def cb_pick_variant(cb: CallbackQuery, repo: RequestsRepo):
    """Выбрать, какую из строк слота правим, и запомнить её weeks."""
    _, _, weekday_s, parity, para_s, idx_s = cb.data.split(":")
    weekday, para, idx = int(weekday_s), int(para_s), int(idx_s)
    group = await editor_group(repo, cb.from_user.id)
    if not group:
        await cb.answer("Нет прав", show_alert=True)
        return
    lessons = await repo.base_lessons.get_day(group, weekday, parity)
    here = [l for l in lessons if l.para == para]
    if idx >= len(here):
        await cb.answer("Устарело", show_alert=True)
        return
    weeks = here[idx].weeks or ""
    await cb.message.edit_text(
        f"{EDITOR_TITLE}\n\n<b>{WEEKDAY_FULL[weekday - 1]}</b>, "
        f"{PARITY_LABELS.get(parity, parity)} неделя, <b>{para} пара</b>\n"
        f"недели: <i>{weeks or 'все'}</i>\n\n"
        f"Сейчас: <b>{here[idx].subject}</b>\n\nЧто делаем? 👇",
        reply_markup=slot_actions_kb(
            weekday, parity, para, has_value=True, weeks=weeks))
    await cb.answer()


@editor_router.callback_query(F.data.startswith("ed:edit:"))
async def cb_edit_base(cb: CallbackQuery, repo: RequestsRepo, state: FSMContext):
    group = await editor_group(repo, cb.from_user.id)
    if not group:
        await cb.answer("Нет прав", show_alert=True)
        return
    parts = cb.data.split(":")
    _, _, weekday_s, parity, para_s = parts[:5]
    weekday, para = int(weekday_s), int(para_s)
    # weeks приходит из кнопки; "_" — «все недели» (пустой список).
    weeks = "" if len(parts) < 6 or parts[5] == "_" else parts[5]

    suggestions = await _subject_suggestions(repo, group)
    await state.update_data(layer="base", weekday=weekday, parity=parity, para=para,
                            weeks=weeks)
    await state.set_state(EditorState.subject)

    await cb.message.edit_text(
        f"{EDITOR_TITLE}\n\n<b>{WEEKDAY_FULL[weekday - 1]}</b>, {para} пара\n\n"
        "✏️ Напиши <b>название предмета</b>.\n\n"
        + _suggest_text(suggestions, "предметы группы"),
        reply_markup=_suggest_kb(suggestions, f"ed:sug:{weekday}:{parity}:{para}",
                                 back=f"ed:bs:{weekday}:{parity}:{para}"),
    )
    await cb.answer()


@editor_router.callback_query(F.data.startswith("ed:sug:"))
async def cb_subject_suggestion(cb: CallbackQuery, repo: RequestsRepo, state: FSMContext):
    _, _, weekday_s, parity, para_s, idx_s = cb.data.split(":")
    data = await state.get_data()
    suggestions = data.get("suggestions") or []
    idx = int(idx_s)
    if idx >= len(suggestions):
        await cb.answer("Устарело", show_alert=True)
        return
    subject = suggestions[idx]
    await state.update_data(subject=subject)
    await cb.message.edit_text(
        f"{EDITOR_TITLE}\n\nПредмет: <b>{escape(subject)}</b>\n\n"
        "👨‍🏫 Теперь напиши <b>фамилию преподавателя</b> или нажми «Пропустить».",
        reply_markup=_skip_kb("ed:skip_teacher"),
    )
    await state.set_state(EditorState.teacher)
    await cb.answer()


@editor_router.callback_query(F.data == "ed:skip_teacher")
async def cb_skip_teacher(cb: CallbackQuery, repo: RequestsRepo, state: FSMContext):
    await state.update_data(teacher="")
    await cb.message.edit_text(
        f"{EDITOR_TITLE}\n\n🚪 Теперь <b>кабинет</b> или нажми «Пропустить».",
        reply_markup=_skip_kb("ed:skip_room"),
    )
    await state.set_state(EditorState.room)
    await cb.answer()


@editor_router.callback_query(F.data == "ed:skip_room")
async def cb_skip_room(cb: CallbackQuery, repo: RequestsRepo, state: FSMContext):
    await state.update_data(room="")
    await _save_base(cb, repo, state, via_cb=True)


async def _save_base(event, repo: RequestsRepo, state: FSMContext, via_cb: bool):
    data = await state.get_data()
    group = await editor_group(repo, event.from_user.id)
    if not group:
        # Права могли отозвать, пока староста вводил три поля. Раньше
        # здесь был голый return: человек проходил весь диалог и на
        # последнем шаге не получал ни ошибки, ни подтверждения.
        text = "Права редактора отозваны. Правка не сохранена."
        if via_cb:
            await event.message.edit_text(text, reply_markup=_no_rights_kb())
        else:
            await event.answer(text, reply_markup=_no_rights_kb())
        await state.clear()
        return
    weekday = data["weekday"]
    parity = data["parity"]
    para = data["para"]
    subject = (data.get("subject") or "").strip()
    teacher = (data.get("teacher") or "").strip()
    room = (data.get("room") or "").strip()

    if not subject:
        text = "❌ Предмет не может быть пустым. Начни заново."
        if via_cb:
            await event.message.edit_text(text, reply_markup=cancel_kb("ed:base"))
        else:
            await event.answer(text)
        await state.clear()
        return

    # `weeks` — часть ключа upsert. У вуза в одном слоте живут
    # несколько дисциплин по разным неделям (на проде 425 слотов), и без
    # weeks upsert не находит строку, делает INSERT, а новая строка
    # видна на всех неделях сразу. Недели выбраны человеком в меню пары.
    weeks = (data.get("weeks") or "")
    old = await repo.base_lessons.get_day(group, weekday, parity)
    old_slot = next((l for l in old
                     if l.para == para and (l.weeks or "") == weeks), None)

    await repo.base_lessons.upsert(group, parity, weekday, para, subject, teacher, room,
                                   source="manual", updated_by=event.from_user.id,
                                   weeks=weeks)
    await repo.edit_log.log(
        group, "base", "edit" if old_slot else "add", user_id=event.from_user.id,
        para=para,
        # Преподавателя и кабинет тоже: cb_undo восстанавливает все три
        # поля, а раньше в журнале лежал только предмет — откат молча
        # стирал преподавателя у 100% пар.
        old_value={"subject": old_slot.subject, "teacher": old_slot.teacher,
                   "room": old_slot.room} if old_slot else None,
        new_value={"weekday": weekday, "parity": parity, "para": para,
                   "subject": subject, "teacher": teacher, "room": room,
                   "weeks": weeks},
    )
    # Правка базы повторяется каждую неделю, но только в свой день и
    # свою чётность — пересобираем два дня окна из четырнадцати.
    rebuilt = await _rebuild(repo, weekday=weekday, parity=parity)
    # Симметрично _save_sub. Без очистки состояние остаётся
    # EditorState.room, и любое следующее сообщение старосты («спасибо»)
    # перезаписывает пару с room="спасибо" — вместе с _rebuild и
    # рассылкой уведомления группе на каждое сообщение.
    await state.clear()

    notified = 0
    try:
        notified = await notify_group_about_edit(
            event.bot, repo, group, None, event.from_user.id)
    except Exception:
        logging.exception("не удалось разослать уведомление о правке базы")

    lessons = await repo.base_lessons.get_day(group, weekday, parity)
    slots = [Slot(l.para, l.subject, l.teacher, l.room) for l in lessons]
    # Не врать про успех: правка уже в слоях, но студент её не увидит,
    # пока поллер не пересоберёт college_lesson сам.
    head = "✅ <b>Сохранено</b>" if rebuilt else (
        "⚠️ <b>Правка сохранена, но расписание не пересобралось</b>\n"
        "Студенты увидят её в течение 5 минут — поллер пересоберёт сам. "
        "Если не появилась, сообщи админу.")
    text = (head
            + (f" · уведомлено: {notified}" if notified else "")
            + "\n\n"
            f"{WEEKDAY_FULL[weekday - 1]}, {PARITY_LABELS.get(parity, parity)} неделя, "
            f"{para} пара → <b>{escape(subject)}</b>\n\n"
            + base_day_text(group, weekday, parity, slots))
    if via_cb:
        await event.message.edit_text(text, reply_markup=paras_kb(weekday, parity, slots, last=max_para(group)))
        await event.answer()
    else:
        await event.answer(text, reply_markup=paras_kb(weekday, parity, slots, last=max_para(group)))


@editor_router.callback_query(F.data.startswith("ed:del:"))
async def cb_del_base(cb: CallbackQuery, repo: RequestsRepo):
    group = await editor_group(repo, cb.from_user.id)
    if not group:
        await cb.answer("Нет прав", show_alert=True)
        return
    parts = cb.data.split(":")
    _, _, weekday_s, parity, para_s = parts[:5]
    weekday, para = int(weekday_s), int(para_s)
    weeks_in = "" if len(parts) < 6 or parts[5] == "_" else parts[5]

    lessons = await repo.base_lessons.get_day(group, weekday, parity)
    old_slot = next((l for l in lessons
                     if l.para == para and (l.weeks or "") == weeks_in), None)
    if old_slot is None:
        await cb.answer("Строка уже изменилась, открой день заново", show_alert=True)
        return
    # `weeks` — часть условия удаления. Без неё delete_slot ищет строку
    # с weeks='' и у вуза не удаляет ничего.
    await repo.base_lessons.delete_slot(group, parity, weekday, para,
                                        weeks=(old_slot.weeks or "") if old_slot else "")
    await repo.edit_log.log(
        group, "base", "delete", user_id=cb.from_user.id, para=para,
        old_value={"subject": old_slot.subject, "teacher": old_slot.teacher,
                   "room": old_slot.room} if old_slot else None,
    )
    await _rebuild(repo, weekday=weekday, parity=parity)
    lessons = await repo.base_lessons.get_day(group, weekday, parity)
    slots = [Slot(l.para, l.subject, l.teacher, l.room) for l in lessons]
    await cb.message.edit_text(
        "🗑 Пара убрана.\n\n" + base_day_text(group, weekday, parity, slots),
        reply_markup=paras_kb(weekday, parity, slots, last=max_para(group)),
    )
    await cb.answer("Убрано")


# --- замены ---------------------------------------------------------------

@editor_router.callback_query(F.data == "ed:subs")
async def cb_subs(cb: CallbackQuery, repo: RequestsRepo, state: FSMContext):
    # Состояние-сирота после «Назад» превращало любой текст в
    # название предмета. Чистим на каждом переходе между экранами.
    await state.clear()
    group = await editor_group(repo, cb.from_user.id)
    if not group:
        await cb.answer("Нет прав", show_alert=True)
        return
    today = datetime.date.today()
    await cb.message.edit_text(
        f"{EDITOR_TITLE}\n\n📅 <b>Замены</b>\n\n"
        "Замены обычно дают на следующий день.\n"
        "🔵 чётная неделя · 🔴 нечётная\n\n"
        "На какую дату? 👇",
        reply_markup=sub_dates_kb(group, today),
    )
    await cb.answer()


async def _render_sub_day(cb: CallbackQuery, repo: RequestsRepo, group: str,
                          date: datetime.date):
    slots = await get_day_slots(repo, group, date)
    subs = await repo.substitutions.get_for_date(group, date)
    subs_by_para = {s.para: s for s in subs}
    await cb.message.edit_text(
        sub_day_text(group, date, slots),
        reply_markup=sub_slots_kb(date.isoformat(), slots, subs_by_para, last=max_para(group)),
    )


@editor_router.callback_query(F.data.startswith("ed:sd:"))
async def cb_sub_date(cb: CallbackQuery, repo: RequestsRepo):
    group = await editor_group(repo, cb.from_user.id)
    if not group:
        await cb.answer("Нет прав", show_alert=True)
        return
    date = datetime.date.fromisoformat(cb.data.split(":")[2])
    await _render_sub_day(cb, repo, group, date)
    await cb.answer()


@editor_router.callback_query(F.data.startswith("ed:sdl:"))
async def cb_sub_day_back(cb: CallbackQuery, repo: RequestsRepo, state: FSMContext):
    # Состояние-сирота после «Назад» превращало любой текст в
    # название предмета. Чистим на каждом переходе между экранами.
    await state.clear()
    group = await editor_group(repo, cb.from_user.id)
    if not group:
        await cb.answer("Нет прав", show_alert=True)
        return
    date = datetime.date.fromisoformat(cb.data.split(":")[2])
    await _render_sub_day(cb, repo, group, date)
    await cb.answer()


@editor_router.callback_query(F.data.startswith("ed:ss:"))
async def cb_sub_slot(cb: CallbackQuery, repo: RequestsRepo):
    group = await editor_group(repo, cb.from_user.id)
    if not group:
        await cb.answer("Нет прав", show_alert=True)
        return
    _, _, date_s, para_s = cb.data.split(":")
    date, para = datetime.date.fromisoformat(date_s), int(para_s)

    slots = await get_day_slots(repo, group, date)
    base_slot = next((s for s in slots if s.para == para and not s.changed), None)
    subs = await repo.substitutions.get_for_date(group, date)
    has_sub = any(s.para == para for s in subs)

    text = (f"{EDITOR_TITLE}\n\n{date.strftime('%d.%m.%Y')}, <b>{para} пара</b>\n\n")
    if base_slot:
        text += f"По базовому расписанию: <b>{base_slot.subject}</b>\n"
    else:
        text += "По базовому расписанию: <i>пары нет</i>\n"
    if has_sub:
        sub = next(s for s in subs if s.para == para)
        if sub.action == SUB_CANCEL:
            text += "Замена: ❌ <b>отменена</b>\n"
        else:
            text += f"Замена: 🔄 <b>{sub.subject}</b>\n"
    text += "\nЧто делаем? 👇"
    await cb.message.edit_text(text, reply_markup=sub_actions_kb(date_s, para, has_sub, base_slot))
    await cb.answer()


@editor_router.callback_query(F.data.startswith("ed:scancel:"))
async def cb_sub_cancel(cb: CallbackQuery, repo: RequestsRepo):
    group = await editor_group(repo, cb.from_user.id)
    if not group:
        await cb.answer("Нет прав", show_alert=True)
        return
    _, _, date_s, para_s = cb.data.split(":")
    date, para = datetime.date.fromisoformat(date_s), int(para_s)

    await repo.substitutions.set(date, group, para, SUB_CANCEL,
                                 created_by=cb.from_user.id)
    await repo.edit_log.log(group, "sub", "edit", user_id=cb.from_user.id,
                            date=date, para=para, new_value={"action": SUB_CANCEL})
    await _rebuild(repo, date)
    await _render_sub_day(cb, repo, group, date)
    await cb.answer("❌ Пара отменена")


@editor_router.callback_query(F.data.startswith("ed:sreset:"))
async def cb_sub_reset(cb: CallbackQuery, repo: RequestsRepo):
    group = await editor_group(repo, cb.from_user.id)
    if not group:
        await cb.answer("Нет прав", show_alert=True)
        return
    _, _, date_s, para_s = cb.data.split(":")
    date, para = datetime.date.fromisoformat(date_s), int(para_s)

    await repo.substitutions.delete(date, group, para)
    await repo.edit_log.log(group, "sub", "delete", user_id=cb.from_user.id,
                            date=date, para=para)
    await _rebuild(repo, date)
    await _render_sub_day(cb, repo, group, date)
    await cb.answer("↩️ Замена снята")


@editor_router.callback_query(F.data.startswith("ed:sedit:"))
@editor_router.callback_query(F.data.startswith("ed:sadd:"))
async def cb_sub_edit(cb: CallbackQuery, repo: RequestsRepo, state: FSMContext):
    group = await editor_group(repo, cb.from_user.id)
    if not group:
        await cb.answer("Нет прав", show_alert=True)
        return
    parts = cb.data.split(":")
    date_s, para_s = parts[2], parts[3]
    date, para = datetime.date.fromisoformat(date_s), int(para_s)
    action = SUB_REPLACE if parts[1] == "sedit" else SUB_ADD

    suggestions = await _subject_suggestions(repo, group)
    await state.update_data(layer="sub", date=date_s, para=para, action=action,
                            suggestions=suggestions)
    await state.set_state(EditorState.subject)

    await cb.message.edit_text(
        f"{EDITOR_TITLE}\n\n{date.strftime('%d.%m.%Y')}, {para} пара\n\n"
        "✏️ Напиши <b>название предмета</b>.\n\n"
        + _suggest_text(suggestions, "предметы группы"),
        reply_markup=_suggest_kb(suggestions, f"ed:ssug:{date_s}:{para}:{action}",
                                 back=f"ed:ss:{date_s}:{para}"),
    )
    await cb.answer()


@editor_router.callback_query(F.data.startswith("ed:ssug:"))
async def cb_sub_subject_suggestion(cb: CallbackQuery, repo: RequestsRepo, state: FSMContext):
    _, _, date_s, para_s, action, idx_s = cb.data.split(":")
    data = await state.get_data()
    suggestions = data.get("suggestions") or []
    idx = int(idx_s)
    if idx >= len(suggestions):
        await cb.answer("Устарело", show_alert=True)
        return
    await state.update_data(subject=suggestions[idx])
    await cb.message.edit_text(
        f"{EDITOR_TITLE}\n\nПредмет: <b>{escape(suggestions[idx])}</b>\n\n"
        "👨‍🏫 Напиши <b>фамилию преподавателя</b> или нажми «Пропустить».",
        reply_markup=_skip_kb("ed:sub_skip_teacher"),
    )
    await state.set_state(EditorState.teacher)
    await cb.answer()


@editor_router.callback_query(F.data == "ed:sub_skip_teacher")
async def cb_sub_skip_teacher(cb: CallbackQuery, repo: RequestsRepo, state: FSMContext):
    await state.update_data(teacher="")
    await cb.message.edit_text(
        f"{EDITOR_TITLE}\n\n🚪 <b>Кабинет</b> или «Пропустить».",
        reply_markup=_skip_kb("ed:sub_skip_room"),
    )
    await state.set_state(EditorState.room)
    await cb.answer()


@editor_router.callback_query(F.data == "ed:sub_skip_room")
async def cb_sub_skip_room(cb: CallbackQuery, repo: RequestsRepo, state: FSMContext):
    await state.update_data(room="")
    await _save_sub(cb, repo, state, via_cb=True)


async def _save_sub(event, repo: RequestsRepo, state: FSMContext, via_cb: bool):
    data = await state.get_data()
    group = await editor_group(repo, event.from_user.id)
    if not group:
        # Права могли отозвать, пока староста вводил три поля. Раньше
        # здесь был голый return: человек проходил весь диалог и на
        # последнем шаге не получал ни ошибки, ни подтверждения.
        text = "Права редактора отозваны. Правка не сохранена."
        if via_cb:
            await event.message.edit_text(text, reply_markup=_no_rights_kb())
        else:
            await event.answer(text, reply_markup=_no_rights_kb())
        await state.clear()
        return
    date = datetime.date.fromisoformat(data["date"])
    para = data["para"]
    action = data.get("action", SUB_REPLACE)
    subject = (data.get("subject") or "").strip()
    teacher = (data.get("teacher") or "").strip()
    room = (data.get("room") or "").strip()

    if not subject:
        msg = "❌ Предмет не может быть пустым. Начни заново."
        if via_cb:
            await event.message.edit_text(msg, reply_markup=cancel_kb("ed:subs"))
        else:
            await event.answer(msg)
        await state.clear()
        return

    # Что было на этом слоте до правки. Без этого «Откатить» для замены
    # просто удалял строку: если поверх уже стояла замена, она была
    # перезаписана set()-ом и больше нигде не хранилась.
    before = await repo.substitutions.get_for_date(group, date)
    old_sub = next((s for s in before if s.para == para), None)

    await repo.substitutions.set(date, group, para, action, subject, teacher, room,
                                 created_by=event.from_user.id)
    rebuilt = await _rebuild(repo, date)
    await repo.edit_log.log(group, "sub", "edit", user_id=event.from_user.id,
                            date=date, para=para,
                            old_value={"action": old_sub.action,
                                       "subject": old_sub.subject,
                                       "teacher": old_sub.teacher,
                                       "room": old_sub.room} if old_sub else None,
                            new_value={
                                "action": action, "subject": subject,
                                "teacher": teacher, "room": room})
    await state.clear()

    notified = 0
    try:
        notified = await notify_group_about_edit(
            event.bot, repo, group, date, event.from_user.id)
    except Exception:
        logging.exception("не удалось разослать уведомление о замене")

    slots = await get_day_slots(repo, group, date)
    subs = await repo.substitutions.get_for_date(group, date)
    subs_by_para = {s.para: s for s in subs}
    head = "✅ <b>Сохранено</b>" if rebuilt else (
        "⚠️ <b>Правка сохранена, но расписание не пересобралось</b>\n"
        "Студенты увидят её в течение 5 минут — поллер пересоберёт сам. "
        "Если не появилась, сообщи админу.")
    text = (head
            + (f" · уведомлено: {notified}" if notified else "")
            + f"\n\n{date.strftime('%d.%m.%Y')}, {para} пара → "
            f"<b>{escape(subject)}</b>\n\n" + sub_day_text(group, date, slots))
    kb = sub_slots_kb(date.isoformat(), slots, subs_by_para, last=max_para(group))
    if via_cb:
        await event.message.edit_text(text, reply_markup=kb)
        await event.answer()
    else:
        await event.answer(text, reply_markup=kb)


# --- предпросмотр и журнал ------------------------------------------------

@editor_router.callback_query(F.data == "ed:preview")
async def cb_preview(cb: CallbackQuery, repo: RequestsRepo, state: FSMContext):
    # Состояние-сирота после «Назад» превращало любой текст в
    # название предмета. Чистим на каждом переходе между экранами.
    await state.clear()
    group = await editor_group(repo, cb.from_user.id)
    if not group:
        await cb.answer("Нет прав", show_alert=True)
        return
    today = datetime.date.today()
    rows = []
    for delta in range(0, 3):
        d = today + datetime.timedelta(days=delta)
        label = "сегодня" if delta == 0 else "завтра" if delta == 1 else d.strftime("%d.%m")
        rows.append([InlineKeyboardButton(
            text=f"{WEEKDAY_SHORT[d.weekday()]} {d.strftime('%d.%m')} ({label})",
            callback_data=f"ed:pv:{d.isoformat()}")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="ed:back")])
    await cb.message.edit_text(
        f"{EDITOR_TITLE}\n\n👁 <b>Как видят студенты</b>\n\nВыбери день 👇",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await cb.answer()


@editor_router.callback_query(F.data.startswith("ed:pv:"))
async def cb_preview_day(cb: CallbackQuery, repo: RequestsRepo):
    group = await editor_group(repo, cb.from_user.id)
    if not group:
        await cb.answer("Нет прав", show_alert=True)
        return
    date = datetime.date.fromisoformat(cb.data.split(":")[2])
    slots = await get_day_slots(repo, group, date)
    # Звонки и поток нужны, чтобы предпросмотр совпадал с экраном дня:
    # без них не подставить время пары и деление на курсы.
    bell, lunches = await repo.bell_schedule.get_context()
    await cb.message.edit_text(
        preview_text(group, date, slots, bell, lunches,
                     bells_group(group, None)),
        reply_markup=cancel_kb("ed:preview"),
    )
    await cb.answer()


def _log_place(e) -> str:
    """Где сделана правка — так, чтобы строки отличались.

    У правок базы даты нет (она повторяется каждую неделю), и в журнале
    все они выглядели одинаково: «база/3 пара». Три правки — пн, ср,
    пт, все третьи пары — давали три неразличимые строки, и староста
    не мог понять, какую откатывать. День недели и чётность уже лежат
    в new_value, их пишет _save_base.
    """
    if e.layer == "base":
        data = _json(e.new_value)
        wd = data.get("weekday")
        # В базе parity лежит как "EVEN"/"ODD", но старые записи и чужие
        # руки могут дать нижний регистр — приводим.
        par = PARITY_LABELS.get(str(data.get("parity") or "").upper(), "")
        day = WEEKDAY_SHORT[wd - 1] if isinstance(wd, int) and 1 <= wd <= 7 else "?"
        return f"база/{day} {par}/{e.para} пара".replace("  ", " ")
    if e.layer == "sub":
        day = e.date.strftime("%d.%m") if e.date else "?"
        return f"замена {day}/{e.para} пара"
    return f"{e.layer}/{e.para} пара"


def _json(raw) -> dict:
    """Разобрать JSON из журнала, не роняя экран.

    Поле VARCHAR(1024) и пишется кодом, но экран правок не должен
    зависать из-за одной битой строки: студент-староста увидит ошибку
    вместо журнала и ничего не откатит.
    """
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


@editor_router.callback_query(F.data == "ed:log")
async def cb_log(cb: CallbackQuery, repo: RequestsRepo, state: FSMContext):
    # Состояние-сирота после «Назад» превращало любой текст в
    # название предмета. Чистим на каждом переходе между экранами.
    await state.clear()
    group = await editor_group(repo, cb.from_user.id)
    if not group:
        await cb.answer("Нет прав", show_alert=True)
        return
    entries = await repo.edit_log.get_recent(group, limit=10)
    lines = [f"{EDITOR_TITLE}", "", "📜 <b>Последние правки</b>", ""]
    if not entries:
        lines.append("<i>Правок ещё не было</i>")
    else:
        for e in entries:
            when = e.created_at.strftime("%d.%m %H:%M") if e.created_at else "—"
            where = _log_place(e)
            lines.append(f"<b>{when}</b> · {where} · {e.action}")
    await cb.message.edit_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="↩️ Откатить последнюю",
                                  callback_data="ed:undo")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="ed:back")],
        ]),
    )
    await cb.answer()


@editor_router.callback_query(F.data == "ed:undo")
async def cb_undo(cb: CallbackQuery, repo: RequestsRepo):
    group = await editor_group(repo, cb.from_user.id)
    if not group:
        await cb.answer("Нет прав", show_alert=True)
        return
    last = await repo.edit_log.get_last(group)
    if not last:
        await cb.answer("Нечего откатывать", show_alert=True)
        return

    if last.layer == "base":
        old = _json(last.old_value)
        new = _json(last.new_value)
        weekday, parity = new.get("weekday"), new.get("parity")

        if last.action == "add":
            # Пары не было — откат значит убрать её совсем. Раньше
            # пробовали вернуть old_value, а он пустой, и пара оставалась
            # на месте: «Откатить» не работало для добавленных пар.
            if weekday and parity:
                await repo.base_lessons.delete_slot(group, parity, weekday, last.para,
                                                    weeks=new.get("weeks", ""))
            msg = "↩️ Добавленная пара убрана"
        elif old.get("subject"):
            if weekday and parity:
                await repo.base_lessons.upsert(
                    group, parity, weekday, last.para, old["subject"],
                    teacher=old.get("teacher", ""), room=old.get("room", ""),
                    source="manual", updated_by=cb.from_user.id,
                    # weeks — часть ключа; без неё откат вузовской правки
                    # создал бы дубль вместо возврата строки.
                    weeks=old.get("weeks", ""))
            msg = f"↩️ Возвращено: <b>{old['subject']}</b>"
        else:
            # Пара была удалена — из журнала её содержимое не восстановить.
            msg = "↩️ Откат: пара была удалена (восстанови вручную)"
        # Студент читает college_lesson, а не слои: без пересборки откат
        # доедет до него только через следующий проход поллера. Для базы
        # пересобираем дни этого weekday и чётности, а не все 14.
        await _rebuild(repo, weekday=weekday, parity=parity)
    else:
        # Замену возвращаем, а не просто снимаем: если поверх уже стояла
        # замена, set() её перезаписал, и удаление стёрло бы обе.
        old = _json(last.old_value) or None
        if old and old.get("subject"):
            await repo.substitutions.set(
                last.date, group, last.para, old.get("action") or "replace",
                old["subject"], old.get("teacher", ""), old.get("room", ""),
                created_by=cb.from_user.id)
            msg = f"↩️ Возвращена замена: <b>{old['subject']}</b>"
        else:
            await repo.substitutions.delete(last.date, group, last.para)
            msg = "↩️ Замена снята"
        await _rebuild(repo, last.date)

    # Запись из журнала убираем: иначе следующее нажатие «Откатить»
    # повторит ту же правку, и кнопка будет выглядеть сломанной.
    await repo.edit_log.delete(last.id)
    await cb.answer(msg, show_alert=True)
    await cb_log(cb, repo)


async def _rebuild(repo: RequestsRepo, date: datetime.date | None = None,
                   weekday: int | None = None, parity: str | None = None) -> bool:
    """Пересобрать college_lesson после правки. ``False`` — не вышло.

    Студент читает готовую таблицу, а не слои. Без пересборки замена
    появлялась у него только после следующего опроса поллера — до пяти
    минут, а если сайт лежал, то вообще никогда.

    ``date`` задан — пересобираем только этот день (правка на дату).
    ``weekday`` задан — только дни окна на этот день недели и чётность:
    правка базы повторяется каждую неделю, но не каждый день, а полная
    пересборка 14 дней блокировала бота на 3.6 с (замер на проде
    27.10: materialize 3.62 с против materialize_day 0.33 с).
    Ничего не задано — все дни окна.

    Возвращает результат, чтобы обработчик не врал «✅ Сохранено», когда
    расписание не пересобралось. Правку при этом не откатываем: она уже
    в слоях и корректна, поллер пересоберёт сам через ≤5 минут.
    """
    from tgbot.services import sync_eios
    try:
        if date is not None:
            await sync_eios.materialize_day(repo, date)
        elif weekday is not None:
            await sync_eios.materialize_weekday(repo, weekday, parity)
        else:
            await sync_eios.materialize(repo)
        return True
    except Exception:
        logging.exception("не удалось пересобрать college_lesson")
        return False


# --- ввод текста ----------------------------------------------------------

def _suggest_text(items: list[str], what: str) -> str:
    if not items:
        return ""
    return f"<i>{what} (нажми, чтобы подставить):</i>"


def _suggest_kb(items: list[str], cb_prefix: str, back: str,
                limit: int = 5) -> InlineKeyboardMarkup:
    rows = []
    for i, item in enumerate(items[:limit]):
        rows.append([InlineKeyboardButton(text=item[:48],
                                          callback_data=f"{cb_prefix}:{i}")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=back)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _skip_kb(cb_data: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭ Пропустить", callback_data=cb_data)],
    ])


async def _subject_suggestions(repo: RequestsRepo, group: str) -> list[str]:
    """Предметы группы — для подстановки одним нажатием."""
    seen: dict[str, int] = {}
    for parity in (PARITY_ODD, PARITY_EVEN, PARITY_ANY):
        for l in await repo.base_lessons.get_week(group, parity):
            subject = (l.subject or "").strip()
            if subject:
                seen[subject] = seen.get(subject, 0) + 1
    return [s for s, _ in sorted(seen.items(), key=lambda kv: -kv[1])]


@editor_router.message(EditorState.subject)
async def on_subject(message: Message, repo: RequestsRepo, state: FSMContext):
    subject = (message.text or "").strip()
    if not subject:
        await message.answer("Напиши название предмета текстом.")
        return
    bad = _too_long(subject, "предмет")
    if bad:
        await message.answer(bad)
        return
    await state.update_data(subject=subject)
    data = await state.get_data()
    await message.answer(
        f"{EDITOR_TITLE}\n\nПредмет: <b>{escape(subject)}</b>\n\n"
        "👨‍🏫 Напиши <b>фамилию преподавателя</b> или нажми «Пропустить».",
        reply_markup=_skip_kb("ed:sub_skip_teacher" if data.get("layer") == "sub"
                              else "ed:skip_teacher"),
    )
    await state.set_state(EditorState.teacher)


@editor_router.message(EditorState.teacher)
async def on_teacher(message: Message, repo: RequestsRepo, state: FSMContext):
    teacher = (message.text or "").strip()
    bad = _too_long(teacher, "преподаватель")
    if bad:
        await message.answer(bad)
        return
    await state.update_data(teacher=teacher)
    # Колбэк по слою, как в on_subject: у базовой правки даты нет, и
    # ed:sub_skip_room падал в _save_sub с KeyError: 'date' — правка
    # терялась молча, без ошибки и без подтверждения.
    data = await state.get_data()
    await message.answer(
        f"{EDITOR_TITLE}\n\n🚪 <b>Кабинет</b> или «Пропустить».",
        reply_markup=_skip_kb("ed:sub_skip_room" if data.get("layer") == "sub"
                              else "ed:skip_room"),
    )
    await state.set_state(EditorState.room)


@editor_router.message(EditorState.room)
async def on_room(message: Message, repo: RequestsRepo, state: FSMContext):
    room = (message.text or "").strip()
    bad = _too_long(room, "кабинет")
    if bad:
        await message.answer(bad)
        return
    await state.update_data(room=room)
    data = await state.get_data()
    if data.get("layer") == "sub":
        await _save_sub(message, repo, state, via_cb=False)
    else:
        await _save_base(message, repo, state, via_cb=False)
