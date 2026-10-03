import datetime
import re

DAYS_OF_WEEK = ("ПН", "ВТ", "СР", "ЧТ", "ПТ", "СБ", "ВС")

MONTHS = {
    1: "янв.", 2: "фев.", 3: "мар.", 4: "апр.", 5: "май", 6: "июн.",
    7: "июл.", 8: "авг.", 9: "сен.", 10: "окт.", 11: "ноя.", 12: "дек.",
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


def format_day(
        date: datetime.date,
        lessons,
        bell: dict[tuple[str, str, int], tuple[datetime.time, datetime.time]],
) -> str:
    header = f"<b>{date.day} {MONTHS[date.month]}, {DAYS_OF_WEEK[date.weekday()]}</b>"
    if not lessons:
        return f"{header}\nНет занятий"

    lines = [header]
    dt = day_type_from_date(date)

    rov = bell.get(("MONDAY", "ALL", 0))
    if dt == "MONDAY" and rov:
        lines.append(f"> {rov[0]:%H:%M} – {rov[1]:%H:%M} Разговоры о важном")

    for lesson in lessons:
        cg = course_group_from_group(lesson.group)
        times = bell.get((dt, cg, lesson.para)) or bell.get((dt, "I_IV", lesson.para))
        if times:
            time_str = f"{times[0]:%H:%M} – {times[1]:%H:%M}"
        else:
            time_str = f"пара {lesson.para}"

        line = f"> {time_str}: {lesson.subject}"
        if lesson.teacher:
            line += f" — {lesson.teacher}"
        if lesson.room:
            line += f" [{lesson.room}]"
        lines.append(line)

    return "\n".join(lines)
