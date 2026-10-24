import datetime
import re

DAYS_OF_WEEK = ("ПН", "ВТ", "СР", "ЧТ", "ПТ", "СБ", "ВС")
WEEKDAY_FULL = ("Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье")
MONTHS_GEN = {
    1: "января", 2: "февраля", 3: "марта", 4: "апреля", 5: "мая", 6: "июня",
    7: "июля", 8: "августа", 9: "сентября", 10: "октября", 11: "ноября", 12: "декабря",
}

DETAIL_BRIEF = "brief"
DETAIL_LUNCH = "lunch"
DETAIL_FULL = "full"
DETAIL_ORDER = [DETAIL_BRIEF, DETAIL_LUNCH, DETAIL_FULL]
DETAIL_LABELS = {DETAIL_BRIEF: "кратко", DETAIL_LUNCH: "с обедом", DETAIL_FULL: "полное"}

BELL_OFF = "off"
BELL_START_END = "start_end"
BELL_FULL = "full"
BELL_ORDER = [BELL_OFF, BELL_START_END, BELL_FULL]
BELL_LABELS = {
    BELL_OFF: "выкл",
    BELL_START_END: "звонок+конец пары",
    BELL_FULL: "звонок+перемена+конец",
}

# --- Слои расписания: базовое (по чётности) + замены ----------------------

PARITY_ODD = "ODD"     # нечётная неделя
PARITY_EVEN = "EVEN"   # чётная неделя
PARITY_ANY = "ANY"     # каждую неделю
PARITY_LABELS = {PARITY_ODD: "нечётная", PARITY_EVEN: "чётная", PARITY_ANY: "любая"}

SUB_REPLACE = "replace"
SUB_CANCEL = "cancel"

# Значок пары, пришедшей из листка замен.
SUB_MARK = "🔄"
SUB_ADD = "add"

SOURCE_SITE = "site"
SOURCE_MANUAL = "manual"


def week_parity(date: datetime.date, parity_offset: int = 0) -> str:
    """Чётность учебной недели по ISO-номеру.

    parity_offset сдвигает отсчёт, если колледж считает иначе, чем ISO
    (например, первая учебная неделя семестра — нечётная).
    """
    week = date.isocalendar().week + parity_offset
    return PARITY_EVEN if week % 2 == 0 else PARITY_ODD


def teacher_base(name: str) -> str:
    return (name or "").split(",")[0].strip()


def teacher_matches(lesson_teacher: str, selected_name: str) -> bool:
    lb = teacher_base(lesson_teacher)
    if lb == selected_name:
        return True
    ls = lb.split()
    ss = selected_name.split()
    # surname-only lesson («Ляшко») matches selected «Ляшко Д.В.»
    return len(ls) == 1 and len(ss) > 1 and ls[0].casefold() == ss[0].casefold()


def course_from_group(group: str) -> int:
    m = re.search(r"(\d{2})", group)
    if not m:
        return 1
    admission = 2000 + int(m.group(1))
    now = datetime.datetime.now()
    acad_start = now.year if now.month >= 9 else now.year - 1
    return max(1, min(acad_start - admission + 1, 4))


def course_group_from_group(group: str) -> str:
    course = course_from_group(group)
    # "I_IV" = 1 и 4 курс, "II_III" = 2 и 3 курс
    return "I_IV" if course in (1, 4) else "II_III"


def course_group_from_course(course: int | None) -> str | None:
    if not course:
        return None
    return "I_IV" if course in (1, 4) else "II_III"


def day_type_from_date(date: datetime.date) -> str:
    return "MONDAY" if date.weekday() == 0 else "OTHER"


def _para_brief(bs) -> str:
    return f"{bs.start:%H:%M}–{bs.end:%H:%M}"


def _para_full(bs, lunch) -> str:
    if bs.h1_end == bs.h2_start:
        return f"{bs.start:%H:%M}–{bs.end:%H:%M}"
    first = f"{bs.start:%H:%M}–{bs.h1_end:%H:%M}"
    second = f"{bs.h2_start:%H:%M}–{bs.end:%H:%M}"
    if lunch and lunch.position == "inside":
        return f"{first} / 🍽 {lunch.lunch_start:%H:%M}–{lunch.lunch_end:%H:%M} / {second}"
    return f"{first} / {second}"


def _lunch_line(lunch) -> str:
    return f"🍽 Обед {lunch.lunch_start:%H:%M}–{lunch.lunch_end:%H:%M}"


def format_day(
        date: datetime.date,
        lessons,
        bell,
        lunches,
        detail: str = DETAIL_BRIEF,
        meta: str = "teacher",
        show_rov: bool = True,
        group_course_group: dict[str, str] | None = None,
) -> str:
    header = f"📅 <b>{WEEKDAY_FULL[date.weekday()]}, {date.day} {MONTHS_GEN[date.month]}</b>"
    if not lessons:
        return empty_day(date)

    lines = [header, ""]
    dt = day_type_from_date(date)

    rov = bell.get(("MONDAY", "ALL", 0))
    if show_rov and dt == "MONDAY" and rov:
        lines.append(f"<b>{rov.start:%H:%M}–{rov.end:%H:%M}</b>  Разговоры о важном 🇷🇺")

    for lesson in lessons:
        cg = (group_course_group or {}).get(lesson.group) or course_group_from_group(lesson.group)
        lunch = lunches.get((dt, cg)) or lunches.get((dt, "I_IV"))
        para_end = getattr(lesson, "para_end", None) or lesson.para
        for p in range(lesson.para, para_end + 1):
            bs = bell.get((dt, cg, p)) or bell.get((dt, "I_IV", p))
            if not bs:
                time_str = f"пара {p}"
            elif detail == DETAIL_FULL:
                inline = lunch if (lunch and lunch.position == "inside" and lunch.para == p) else None
                time_str = _para_full(bs, inline)
            else:
                time_str = _para_brief(bs)

            # Значок замены: студент должен видеть, что пара не по
            # постоянному плану. Одна точка — подхватывают и день,
            # и неделя, и рассылка, и уведомления: они все идут сюда.
            mark = f" {SUB_MARK}" if getattr(lesson, "changed", False) else ""
            line = f"{p}) <b>{time_str}</b>  {lesson.subject}{mark}"
            lines.append(line)
            if meta == "group":
                m = " · ".join(x for x in (lesson.group, lesson.room) if x)
            else:
                m = " · ".join(x for x in (lesson.teacher, lesson.room) if x)
            if m:
                lines.append(m)

            if lunch and lunch.para == p and (
                    detail == DETAIL_LUNCH
                    or (detail == DETAIL_FULL and lunch.position == "after")
            ):
                lines.append(_lunch_line(lunch))

    return "\n".join(lines)


def day_header(date: datetime.date) -> str:
    """Единый заголовок дня для всех состояний."""
    return f"📅 <b>{WEEKDAY_FULL[date.weekday()]}, {date.day} {MONTHS_GEN[date.month]}</b>"


def empty_day(date: datetime.date, note: str | None = None) -> str:
    """Единая точка для состояния «пар нет».

    Используется и format_day (пустой список), и format_no_lessons,
    чтобы текст не расходился между вызовами.
    """
    text = f"{day_header(date)}\n\nЗанятий нет 🙌"
    if note:
        text += f"\n<i>{note}</i>"
    return text


def format_not_published(date: datetime.date) -> str:
    return f"{day_header(date)}\n\nРасписание ещё не выложено ⏳"


def format_no_lessons(date: datetime.date, note: str | None = None) -> str:
    return empty_day(date, note)


def format_stale_warning(when: datetime.datetime | None) -> str:
    """Предупреждение, что замены давно не проверялись.

    Не заменяет расписание, а дописывается к нему: постоянное расписание
    у нас есть и оно верное, но замены с сайта могли появиться, а мы о них
    не знаем. Молчать об этом нельзя — студент придёт не туда.
    """
    if when is None:
        return ("\n\n⚠️ <i>Расписание с сайта ни разу не загрузилось. "
                "Замены не проверены.</i>")
    return (f"\n\n⚠️ <i>Сайт колледжа не отвечает с {when:%d.%m %H:%M}. "
            f"Замены с тех пор не проверены — они могли появиться.</i>")


def format_unverified(date: datetime.date, when: datetime.datetime | None) -> str:
    """Пар нет, но и сайт недоступен — нельзя утверждать, что их нет.

    Отличается от format_no_lessons принципиально: там мы уверены, что
    занятий нет, здесь — просто не знаем.
    """
    return (f"{day_header(date)}\n\n"
            f"Занятий нет по постоянному расписанию 📋"
            f"{format_stale_warning(when)}")


def format_week(entries, bell, lunches, detail: str = DETAIL_BRIEF, meta: str = "teacher", show_rov: bool = True, group_course_group: dict[str, str] | None = None) -> str:
    if not entries:
        return "На этой неделе расписания пока нет 📭"
    return "\n\n".join(format_day(d, les, bell, lunches, detail, meta, show_rov, group_course_group) for d, les in entries)


def format_teacher_results(entries, bell, lunches, detail: str = DETAIL_BRIEF) -> str:
    parts = []
    for date, lessons in entries:
        parts.append(format_day(date, lessons, bell, lunches, detail, meta="group", show_rov=False))
    return "\n\n".join(parts)


def format_bell(bell, lunches) -> str:
    lines = ["⏰ <b>Расписание звонков</b>\n"]
    for day_type, title in [("MONDAY", "Понедельник"), ("OTHER", "Остальные дни")]:
        lines.append(f"<b>{title}</b>")
        rov = bell.get((day_type, "ALL", 0))
        if rov:
            lines.append(f"🇷🇺 Разговоры о важном · {rov.start:%H:%M}–{rov.end:%H:%M}")
        for cg, label in [("I_IV", "1 и 4 курс"), ("II_III", "2 и 3 курс")]:
            lunch = lunches.get((day_type, cg))
            paras = [bell[(day_type, cg, p)] for p in range(1, 6) if (day_type, cg, p) in bell]
            if not paras:
                continue
            lines.append(f"<b>{label}</b>")
            for bs in paras:
                inline = lunch if (lunch and lunch.position == "inside" and lunch.para == bs.para) else None
                lines.append(f"{bs.para} пара  {_para_full(bs, inline)}")
                if lunch and lunch.position == "after" and lunch.para == bs.para:
                    lines.append(f"🍽 обед {lunch.lunch_start:%H:%M}–{lunch.lunch_end:%H:%M}")
        lines.append("")
    return "\n".join(lines)
