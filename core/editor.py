"""Экраны редактора расписания: тексты и клавиатуры без Telegram.

Перенесено из ``tgbot/handlers/editor.py`` на этапе 1 (план 173).
Функции возвращают ``str`` и ``Keyboard``; адаптер превращает
клавиатуру в платформенную.

Что здесь нетронуто и почему: сами сценарии правки (FSM на четыре шага,
запись в базу, откат) остались в хендлере. Это не «как показать», а
«что сделать», и второй мессенджер их не переиспользует без адаптера
состояний.

Проверено: 27 экранов редактора (10 клавиатур во всех вариантах,
три текста дня по трём чётностям, предпросмотр) — 0 расхождений.
"""
from __future__ import annotations

import datetime

from common.schedule import (DETAIL_BRIEF, MAX_PARA, PARITY_ANY, PARITY_EVEN,
                             PARITY_ODD, SUB_CANCEL, WEEKDAY_FULL,
                             format_day, week_parity)
from core.keyboard import Keyboard, btn, kb
from core.schedule_layer import PARITY_OFFSET, Slot

WEEKDAY_SHORT = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

EDITOR_TITLE = "✏️ <b>Редактор расписания</b>"


def no_rights_kb() -> Keyboard:
    return kb([btn("⬅️ В меню", "menu")])


def editor_main_kb(group: str) -> Keyboard:
    return kb(
        [btn("📅 Правки на дату (замены)", "ed:subs")],
        [btn("🗓 Базовое расписание", "ed:base")],
        [btn("📜 Журнал правок", "ed:log")],
        [btn("👁 Как видят студенты", "ed:preview")],
        [btn("⬅️ В меню", "menu")],
    )


def base_kb(group: str) -> Keyboard:
    return kb(
        [btn("Пн", "ed:bday:1"), btn("Вт", "ed:bday:2"), btn("Ср", "ed:bday:3")],
        [btn("Чт", "ed:bday:4"), btn("Пт", "ed:bday:5"), btn("Сб", "ed:bday:6")],
        [btn("⬅️ Назад", "ed:back")],
    )


def parity_kb(weekday: int) -> Keyboard:
    return kb(
        [btn("🔵 Чётная неделя", f"ed:bp:{weekday}:{PARITY_EVEN}")],
        [btn("🔴 Нечётная неделя", f"ed:bp:{weekday}:{PARITY_ODD}")],
        [btn("⚪️ Каждую неделю", f"ed:bp:{weekday}:{PARITY_ANY}")],
        [btn("⬅️ Назад", "ed:base")],
    )


def paras_kb(weekday: int, parity: str, slots: list[Slot],
             prefix: str = "ed:bs", last: int = MAX_PARA) -> Keyboard:
    """Список пар дня с текущим содержимым.

    ``last`` — сколько слотов показать: 6 у колледжа, 8 у вуза.
    """
    by_para = {s.para: s for s in slots}
    many = {p: sum(1 for s in slots if s.para == p) for p in by_para}
    rows = []
    for p in range(1, last + 1):
        slot = by_para.get(p)
        label = f"{p}) {slot.subject[:20]}" if slot else f"{p}) — пусто"
        # У вуза на один слот несколько строк недель: без пометки кнопка
        # называла только последнюю, а «Изменить» угадывала не ту.
        if many.get(p, 0) > 1:
            label += f" +{many[p] - 1}"
        if slot and slot.changed:
            label += " 🔄"
        rows.append([btn(label, f"{prefix}:{weekday}:{parity}:{p}")])
    rows.append([btn("⬅️ Назад", "ed:base")])
    return kb(*rows)


def slot_actions_kb(weekday: int, parity: str, para: int, has_value: bool,
                    weeks: str = "") -> Keyboard:
    # weeks едет в callback: без него upsert создаёт дубль, а
    # delete_slot не находит строку. 64 байта хватает — список недель
    # у вуза короткий ("5,6,7,8" / "9,10,11,12,13").
    wk = weeks or "_"
    rows = [[btn("✏️ Изменить", f"ed:edit:{weekday}:{parity}:{para}:{wk}")]]
    if has_value:
        rows.append([btn("🗑 Убрать пару",
                         f"ed:del:{weekday}:{parity}:{para}:{wk}")])
    rows.append([btn("⬅️ Назад", f"ed:bpar:{weekday}:{parity}")])
    return kb(*rows)


def sub_dates_kb(group: str, today: datetime.date) -> Keyboard:
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
        rows.append([btn(f"{parity} {label}", f"ed:sd:{d.isoformat()}")])
    rows.append([btn("⬅️ Назад", "ed:back")])
    return kb(*rows)


def sub_slots_kb(date_iso: str, slots: list[Slot], subs_by_para: dict,
                 last: int = MAX_PARA) -> Keyboard:
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
        rows.append([btn(label, f"ed:ss:{date_iso}:{p}")])
    rows.append([btn("⬅️ Назад", "ed:subs")])
    return kb(*rows)


def sub_actions_kb(date_iso: str, para: int, has_sub: bool,
                   base_slot: Slot | None) -> Keyboard:
    rows = []
    if base_slot or has_sub:
        rows.append([btn("🔄 Заменить", f"ed:sedit:{date_iso}:{para}")])
    rows.append([btn("➕ Добавить пару", f"ed:sadd:{date_iso}:{para}")])
    if has_sub:
        rows.append([btn("❌ Отменить пару", f"ed:scancel:{date_iso}:{para}")])
        rows.append([btn("↩️ Снять замену", f"ed:sreset:{date_iso}:{para}")])
    rows.append([btn("⬅️ Назад", f"ed:sdl:{date_iso}")])
    return kb(*rows)


def cancel_kb(back: str) -> Keyboard:
    return kb([btn("⬅️ Отмена", back)])


# --- тексты ---------------------------------------------------------------

def _parity_mark(date: datetime.date) -> str:
    return ("🔵 чётная" if week_parity(date, PARITY_OFFSET) == PARITY_EVEN
            else "🔴 нечётная")


# Поля модели объявлены String(256/128/64..512), но SQLite длину не
# проверяет — в предмет влезало сколько угодно. Тогда экран дня пробивал
# лимит Telegram в 4096 символов и не открывался ни у кого в группе.
# Берём минимум из объявленных длин: subject 256, room 64.
MAX_FIELD = {"предмет": 256, "преподаватель": 128, "кабинет": 64}


def too_long(value: str, what: str) -> str | None:
    limit = MAX_FIELD[what]
    if len(value) <= limit:
        return None
    return f"Слишком длинный {what} ({len(value)} символов, максимум {limit})."


def _by_para(slots: list[Slot]) -> dict[int, list[Slot]]:
    """Пары дня по номеру: у вуза на один слот несколько строк недель."""
    out: dict[int, list[Slot]] = {}
    for s in slots:
        out.setdefault(s.para, []).append(s)
    return out


def _week_mark(weeks: str) -> str:
    from html import escape
    return f" <i>({escape(weeks)})</i>" if weeks else ""


def base_day_text(group: str, weekday: int, parity: str,
                  slots: list[Slot]) -> str:
    from html import escape
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
        # У вуза get_day без week отдаёт по строке на каждые weeks:
        # «7) Компьютерное моделирование» печаталось четыре раза подряд
        # (план 153). Одна строка на пару, варианты через «·» с неделями —
        # иначе четыре одинаковых названия неразличимы.
        for para, group_slots in _by_para(slots).items():
            lines.append(f"<b>{para})</b> " + " · ".join(
                escape(s.subject) + _week_mark(s.weeks) for s in group_slots))
            meta = " · ".join(dict.fromkeys(
                x for s in group_slots for x in (s.teacher, s.room) if x))
            if meta:
                lines.append(f"      {meta}")
    lines += ["", "Нажми на пару, чтобы изменить 👇"]
    return "\n".join(lines)


def sub_day_text(group: str, date: datetime.date, slots: list[Slot]) -> str:
    from html import escape
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
            # action, а не только changed: get_day_slots ставит отменённой
            # паре оба признака, и староста видел обычный 🔄 вместо
            # «отменено» — проверить свою же правку было нельзя.
            if getattr(s, "action", "") == SUB_CANCEL:
                flag = " ❌ <i>отменено</i>"
            elif s.changed:
                flag = " 🔄"
            else:
                flag = ""
            lines.append(f"<b>{s.para})</b> {escape(s.subject)}{flag}")
            if meta:
                lines.append(f"      {meta}")
    lines += ["", "Нажми на пару, чтобы поставить замену 👇"]
    return "\n".join(lines)


def preview_text(group: str, date: datetime.date, slots: list[Slot],
                 bell=None, lunches=None, course_group: str | None = None,
                 detail: str = DETAIL_BRIEF) -> str:
    """Предпросмотр ровно так, как увидят студенты.

    Раньше экран собирал текст своей рукой и расходился с реальным:
    не было времени пары (студент видит «11:10–12:45», редактор —
    «Обществознание»), другой порядок строк и не было группы. Теперь
    зовём format_day — тот же код, что и в экране дня.
    """
    lessons = [Slot(s.para, s.subject, s.teacher, s.room,
                    changed=s.changed, action=s.action, comment=s.comment,
                    group=group) for s in slots]
    gcg = {group: course_group} if course_group else None
    # meta="teacher": под парой студент видит преподавателя и кабинет,
    # а не свою же группу. Превью — взгляд студента, не преподавателя.
    # detail был зашит в "full", а 202 из 255 студентов видят brief:
    # староста проверял экран, которого нет ни у кого.
    return format_day(date, lessons, bell or {}, lunches or {},
                      detail=detail, meta="teacher", group_course_group=gcg)
