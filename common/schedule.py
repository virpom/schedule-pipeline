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


def format_day(date: datetime.date, lessons, bell, lunches, detail: str = DETAIL_BRIEF) -> str:
    header = f"📅 <b>{WEEKDAY_FULL[date.weekday()]}, {date.day} {MONTHS_GEN[date.month]}</b>"
    if not lessons:
        return f"{header}\n\nЗанятий нет 🙌"

    lines = [header, ""]
    dt = day_type_from_date(date)
    cg = course_group_from_group(lessons[0].group)
    lunch = lunches.get((dt, cg)) or lunches.get((dt, "I_IV"))

    rov = bell.get(("MONDAY", "ALL", 0))
    if dt == "MONDAY" and rov:
        lines.append(f"<b>{rov.start:%H:%M}–{rov.end:%H:%M}</b>  Разговоры о важном 🇷🇺")

    for lesson in lessons:
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

            line = f"<b>{time_str}</b>  {lesson.subject}"
            lines.append(line)
            meta = " · ".join(x for x in (lesson.teacher, lesson.room) if x)
            if meta:
                lines.append(meta)

            if lunch and lunch.para == p and (
                    detail == DETAIL_LUNCH
                    or (detail == DETAIL_FULL and lunch.position == "after")
            ):
                lines.append(_lunch_line(lunch))

    return "\n".join(lines)


def format_week(entries, bell, lunches, detail: str = DETAIL_BRIEF) -> str:
    if not entries:
        return "На этой неделе расписания пока нет 📭"
    return "\n\n".join(format_day(d, les, bell, lunches, detail) for d, les in entries)


def format_teacher_results(entries, bell, lunches) -> str:
    parts = []
    for date, lessons in entries:
        dt = day_type_from_date(date)
        lines = [f"📅 <b>{WEEKDAY_FULL[date.weekday()]}, {date.day} {MONTHS_GEN[date.month]}</b>"]
        for l in lessons:
            cg = course_group_from_group(l.group)
            para_end = getattr(l, "para_end", None) or l.para
            for p in range(l.para, para_end + 1):
                bs = bell.get((dt, cg, p)) or bell.get((dt, "I_IV", p))
                time_str = _para_brief(bs) if bs else f"пара {p}"
                lines.append(f"<b>{time_str}</b>  {l.subject}")
                meta = " · ".join(x for x in (l.group, l.room) if x)
                if meta:
                    lines.append(meta)
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


def format_bell(bell, lunches) -> str:
    lines = ["⏰ <b>Расписание звонков</b>\n"]
    for day_type, title in [("MONDAY", "Понедельник"), ("OTHER", "Остальные дни")]:
        lines.append(f"<b>{title}</b>")
        rov = bell.get((day_type, "ALL", 0))
        if rov:
            lines.append(f"🇷🇺 Разговоры о важном · {rov.start:%H:%M}–{rov.end:%H:%M}")
        for cg, label in [("I_IV", "I и IV курс"), ("II_III", "II и III курс")]:
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
