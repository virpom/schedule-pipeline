import datetime
import re

DAYS_OF_WEEK = ("ПН", "ВТ", "СР", "ЧТ", "ПТ", "СБ", "ВС")
WEEKDAY_FULL = ("Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье")
MONTHS_GEN = {
    1: "января", 2: "февраля", 3: "марта", 4: "апреля", 5: "мая", 6: "июня",
    7: "июля", 8: "августа", 9: "сентября", 10: "октября", 11: "ноября", 12: "декабря",
}


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


def _time(bell, dt, cg, para):
    t = bell.get((dt, cg, para)) or bell.get((dt, "I_IV", para))
    return f"{t[0]:%H:%M}–{t[1]:%H:%M}" if t else f"пара {para}"


def format_day(
        date: datetime.date,
        lessons,
        bell: dict[tuple[str, str, int], tuple[datetime.time, datetime.time]],
) -> str:
    header = f"📅 <b>{WEEKDAY_FULL[date.weekday()]}, {date.day} {MONTHS_GEN[date.month]}</b>"
    if not lessons:
        return f"{header}\n\nЗанятий нет 🙌"

    lines = [header, ""]
    dt = day_type_from_date(date)

    rov = bell.get(("MONDAY", "ALL", 0))
    if dt == "MONDAY" and rov:
        lines.append(f"<b>{rov[0]:%H:%M}–{rov[1]:%H:%M}</b>  Разговоры о важном 🇷🇺")

    for lesson in lessons:
        cg = course_group_from_group(lesson.group)
        time_str = _time(bell, dt, cg, lesson.para)
        line = f"<b>{time_str}</b>  {lesson.subject}"
        if lesson.teacher:
            line += f" — {lesson.teacher}"
        if lesson.room:
            line += f" · {lesson.room}"
        lines.append(line)

    return "\n".join(lines)


def format_week(entries, bell) -> str:
    if not entries:
        return "На этой неделе расписания пока нет 📭"
    return "\n\n".join(format_day(d, les, bell) for d, les in entries)


def format_bell(items) -> str:
    by_day = {"MONDAY": {}, "OTHER": {}}
    for b in items:
        by_day[b.day_type].setdefault(b.course_group, []).append(b)

    lines = ["⏰ <b>Расписание звонков</b>\n"]
    for day_type, title in [("MONDAY", "Понедельник"), ("OTHER", "Остальные дни")]:
        d = by_day[day_type]
        lines.append(f"<b>{title}</b>")
        if "ALL" in d:
            b = d["ALL"][0]
            lines.append(f"Разговоры о важном: {b.start:%H:%M}–{b.end:%H:%M}")
        for cg, label in [("I_IV", "I и IV курс"), ("II_III", "II и III курс")]:
            if cg in d:
                ps = "  ".join(
                    f"{b.para}) {b.start:%H:%M}–{b.end:%H:%M}"
                    for b in sorted(d[cg], key=lambda x: x.para)
                )
                lines.append(f"{label}: {ps}")
        lines.append("")
    return "\n".join(lines)
