import datetime
import re
from html import escape

DAYS_OF_WEEK = ("ПН", "ВТ", "СР", "ЧТ", "ПТ", "СБ", "ВС")
# Последняя пара дня. Шестая бывает: в звонках для неё есть строка
# (OTHER/I_IV, para=6), в college_lesson — три пары в истории. Жёсткий
# range(1, 6) обрезал её в трёх местах: сетку звонков и две клавиатуры
# редактора. Одна константа вместо трёх копий числа.
MAX_PARA = 6
# У вуза сетка на восемь пар (_format_bell_vuz перебирает range(1, 9)),
# у колледжа на шесть. Редактору нужна граница по группе, а не одна на
# всех: иначе староста вуза видит 5 слотов из 8 и не может править пары
# 6–8 — на проде это 572 пары.
MAX_PARA_VUZ = 8
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

# Группы вуза живут в тех же таблицах, что и колледж, и различаются
# суффиксом. Коллизия реальна: ЭК-23/24/25 есть и там, и там, но это
# разные люди. Суффикс в ключе даёт разделение без миграции таблиц.
VUZ_SUFFIX = "@vuz"
VUZ_GROUP = "VUZ"


def max_para(group: str | None) -> int:
    """Сколько пар показывать редактору для этой группы."""
    return MAX_PARA_VUZ if is_vuz(group) else MAX_PARA


def is_vuz(group: str | None) -> bool:
    return bool(group) and group.endswith(VUZ_SUFFIX)


def strip_unit(group: str | None) -> str | None:
    """Имя группы без служебного суффикса — то, что видит человек."""
    if not group:
        return group
    return group[: -len(VUZ_SUFFIX)] if is_vuz(group) else group
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
    """Фамилия с инициалами без служебного хвоста.

    Пробелы внутри инициалов схлопываются: в файлах вуза встречаются оба
    варианта — «Кокошка И.П.» и «Кокошка И. П.», — и без нормализации
    один человек попадал в список преподавателей дважды.
    """
    head = (name or "").strip()
    # Дефис и тире с пробелами вокруг — то же самое, что без них:
    # на проде «Мурашова-Росс А.В.» и «Мурашова - Росс А.В.» это один
    # человек, а список преподавателей показывал две записи.
    head = re.sub(r"\s*[-–—]\s*", "-", head)
    # Запятая бывает двух родов. «Ляшко Д.В., 1-ая подгруппа» — хвост,
    # его отрезаем. «Багомедова У.М., Левочкина Н.А.» — второй человек, и
    # раньше он терялся целиком (такая строка есть на проде). Отличаем
    # по виду второй части: фамилия с инициалами начинается с заглавной
    # буквы и содержит точку.
    parts = [part.strip() for part in head.split(",") if part.strip()]
    if len(parts) > 1:
        people = [parts[0]] + [p for p in parts[1:]
                               if re.match(r"^[А-ЯЁA-Z][а-яёa-z]+\s+[А-ЯЁA-Z]\.", p)]
        head = ", ".join(people)
    head = re.sub(r"\s+", " ", head)
    # «Кокошка И. П.» и «Кокошка И.П.» — один человек. Убираем пробел
    # после точки внутри инициалов, иначе в списке два одинаковых имени.
    return re.sub(r"(?<=\b[А-ЯЁA-Z]\.)\s+(?=[А-ЯЁA-Z]\.)", "", head)


def teacher_matches(lesson_teacher: str, selected_name: str) -> bool:
    """Совпадает ли преподаватель пары с выбранным.

    Сравнение идёт по фамилии и, если они есть у обеих сторон, по
    инициалам: в расписании имя записано по-разному («Коленова В.А.» и
    «Коленова В. А.»), а человек ищет просто «Коленова». Без сверки
    инициалов однофамильцы видели чужие пары.
    """
    lb = teacher_base(lesson_teacher)
    if lb == selected_name:
        return True
    # В паре бывает двое: «Багомедова У.М., Левочкина Н.А.». Сравнение
    # идёт с каждым по отдельности, иначе вторую нельзя найти поиском.
    if "," in lb:
        return any(teacher_matches(part, selected_name) for part in lb.split(","))
    ls = lb.split()
    ss = selected_name.split()
    if not ls or not ss:
        return False
    if ls[0].casefold() != ss[0].casefold():
        return False
    # Сверяем только общие инициалы: у одного человека в источниках
    # бывает «Городиский В.» и «Городиский В.В.».
    li = [c.casefold() for c in re.findall(r"[А-ЯЁA-Z]", " ".join(ls[1:]))]
    si = [c.casefold() for c in re.findall(r"[А-ЯЁA-Z]", " ".join(ss[1:]))]
    if not li or not si:
        return True          # ищем по фамилии — так и задумано
    n = min(len(li), len(si))
    return li[:n] == si[:n]


def course_from_group(group: str) -> int:
    m = re.search(r"(\d{2})", group)
    if not m:
        return 1
    admission = 2000 + int(m.group(1))
    now = datetime.datetime.now()
    acad_start = now.year if now.month >= 9 else now.year - 1
    return max(1, min(acad_start - admission + 1, 4))


def course_group_from_group(group: str) -> str:
    # У вуза своя сетка звонков: 8 пар, последняя до 22:00. Деление на
    # потоки по курсам там не нужно — время одинаковое для всех.
    if is_vuz(group):
        return VUZ_GROUP
    course = course_from_group(group)
    # "I_IV" = 1 и 4 курс, "II_III" = 2 и 3 курс
    return "I_IV" if course in (1, 4) else "II_III"


def course_group_from_course(course: int | None) -> str | None:
    if not course:
        return None
    return "I_IV" if course in (1, 4) else "II_III"


def bells_group(group: str | None, course: int | None = None) -> str | None:
    """Поток звонков для группы с учётом подразделения.

    У вуза своя сетка (8 пар до 22:00), у колледжа — деление по курсам.
    Раньше везде звали ``course_group_from_course(course)``, и студент
    вуза получал звонки колледжа: пары заканчивались в 22:00, а бот
    показывал время до 15:20.
    """
    # course_group_from_group уже знает про @vuz — здесь только выбор
    # источника: группа точнее курса.
    if group:
        return course_group_from_group(group)
    return course_group_from_course(course)


def day_type_from_date(date: datetime.date) -> str:
    return "MONDAY" if date.weekday() == 0 else "OTHER"


def _para_brief(bs) -> str:
    return f"{bs.start:%H:%M}–{bs.end:%H:%M}"


def _is_para_number_note(note: str, para: int) -> bool:
    """«5-я пара» при para=5 — не время, а подтверждение номера."""
    m = re.fullmatch(r"(\d+)-?я?\s*пара", note.strip().lower())
    return bool(m) and int(m.group(1)) == para


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


def _merge_groups(lessons) -> list:
    """Склеить пары одного преподавателя на один слот.

    Физкультура идёт потоком: шесть групп, один препод, одна пара. В
    расписании это шесть строк подряд с одинаковым временем и
    предметом, и преподаватель видел их как шесть разных пар.

    Пары склеиваются, когда совпадают номер пары, конец пары, предмет
    и преподаватель, — группы дописываются в ``group`` через запятую.

    Кабинеты тоже дописываются. Раньше оставался кабинет первой группы,
    а комментарий обещал обратное («терять её всё равно нельзя — она
    останется от первой группы»): студент второй группы шёл не туда.
    На проде 3 таких слота, напр. «Начертательная геометрия», Лаговская
    Е.В., М-310 и М-103.
    """
    merged: dict[tuple, object] = {}
    for lesson in lessons:
        key = (lesson.para, getattr(lesson, "para_end", None) or lesson.para,
               lesson.subject, teacher_base(lesson.teacher))
        seen = merged.get(key)
        if seen is None:
            merged[key] = lesson
            continue
        # Одна и та же группа попадает дважды: у вуза на один слот
        # бывает несколько пар с разными списками недель, и после
        # фильтра по неделе они приходят как отдельные строки. Без
        # дедупликации в подписи было «СА - 26-2, СА - 26-2».
        groups = [g for g in (getattr(seen, "group", None),
                              getattr(lesson, "group", None)) if g]
        seen.group = ", ".join(dict.fromkeys(
            part.strip() for g in groups for part in g.split(",") if part.strip()))
        # Кабинеты по различию: у потока они обычно общие, но бывают и
        # разные, и тогда молча показать первый — послать не туда.
        rooms = [r for r in (getattr(seen, "room", None),
                             getattr(lesson, "room", None)) if r]
        if len(set(rooms)) > 1:
            seen.room = ", ".join(dict.fromkeys(
                part.strip() for r in rooms for part in r.split(",") if part.strip()))
    return list(merged.values())


def format_day(
        date: datetime.date,
        lessons,
        bell,
        lunches,
        detail: str = DETAIL_BRIEF,
        meta: str = "teacher",
        show_rov: bool = True,
        group_course_group: dict[str, str] | None = None,
        merge_groups: bool = False,
) -> str:
    header = f"📅 <b>{WEEKDAY_FULL[date.weekday()]}, {date.day} {MONTHS_GEN[date.month]}</b>"
    if not lessons:
        return empty_day(date)

    lines = [header, ""]
    dt = day_type_from_date(date)
    if merge_groups:
        lessons = _merge_groups(lessons)

    # «Разговоры о важном» — линейка колледжа, в 9:00 по понедельникам.
    # У вуза её нет, а звонок лежит в общей таблице с course_group='ALL',
    # поэтому без проверки он попадал в расписание студента вуза.
    rov = bell.get(("MONDAY", "ALL", 0))
    if show_rov and dt == "MONDAY" and rov and not is_vuz(getattr(lessons[0], "group", None)):
        lines.append(f"<b>{rov.start:%H:%M}–{rov.end:%H:%M}</b>  Разговоры о важном 🇷🇺")

    for lesson in lessons:
        grp = getattr(lesson, "group", None)
        cg = ((group_course_group or {}).get(grp)
              or course_group_from_group(grp) if grp else None)
        # У вуза своего обеда нет вообще, а строки с course_group='VUZ'
        # в bell_lunch ноль. Запасная ветка на I_IV вставляла обед
        # колледжа внутрь вузовской пары: 11:05 -> 11:30 (обед) -> 11:15.
        lunch = lunches.get((dt, cg))
        if lunch is None and cg != VUZ_GROUP:
            lunch = lunches.get((dt, "I_IV"))
        para_end = getattr(lesson, "para_end", None) or lesson.para
        # Спаренная пара — одно занятие на два часа. Печатаем одной
        # строкой «1–2) 09:00–12:40», а не двумя с перерывом между ними:
        # студент читал это как два разных предмета подряд.
        paired = para_end > lesson.para
        for p in range(lesson.para, para_end + 1):
            bs = bell.get((dt, cg, p)) or bell.get((dt, "I_IV", p))
            # Время из самой ячейки сильнее звонка: пять пар колледжа
            # идут не по сетке, и студент, прочитав звонок, приходил на
            # два часа раньше. «5-я пара» — не время, а подтверждение
            # номера: такой note дублирует звонок и только шумит.
            note = (getattr(lesson, "time_note", "") or "").strip()
            if note and not _is_para_number_note(note, p):
                time_str = note
            elif not bs:
                time_str = f"пара {p}"
            elif detail == DETAIL_FULL:
                inline = lunch if (lunch and lunch.position == "inside" and lunch.para == p) else None
                time_str = _para_full(bs, inline)
            else:
                time_str = _para_brief(bs)

            # Значок замены: студент должен видеть, что пара не по
            # постоянному плану. Одна точка — подхватывают и день,
            # и неделя, и рассылка, и уведомления: они все идут сюда.
            if getattr(lesson, "action", "") == SUB_CANCEL:
                # Отменённую пару не выбрасываем из списка: иначе день
                # выглядит пустым, и непонятно — отменили или не было.
                lines.append(f"{p}) <s><b>{time_str}</b>  {_esc(lesson.subject)}</s>"
                             f"  ❌ <i>отменено</i>")
                continue
            mark = f" {SUB_MARK}" if getattr(lesson, "changed", False) else ""
            if paired:
                if p > lesson.para:
                    continue        # строка уже напечатана на первой паре
                bs_last = (bell.get((dt, cg, para_end))
                           or bell.get((dt, "I_IV", para_end)))
                if bs and bs_last and detail != DETAIL_BRIEF:
                    time_str = f"{bs.start:%H:%M}–{bs_last.end:%H:%M}"
                lines.append(f"{lesson.para}–{para_end}) <b>{time_str}</b>"
                             f"  {_esc(lesson.subject)}{mark}")
            else:
                lines.append(f"{p}) <b>{time_str}</b>  {_esc(lesson.subject)}{mark}")
            if meta == "group":
                # Суффикс @vuz — служебный, человеку он не нужен.
                # strip_unit снимает @vuz и с каждого имени в склейке:
                # «АП-25@vuz, ИС-25@vuz» иначе не влезает в строку.
                raw_group = getattr(lesson, "group", "") or ""
                names = ", ".join(strip_unit(g) for g in raw_group.split(", ") if g)
                m = " · ".join(x for x in (names, lesson.room) if x)
            else:
                m = " · ".join(x for x in (lesson.teacher, lesson.room) if x)
            m = _esc(m)
            if m:
                lines.append(m)
            # Две пары на одном номере — параллельные подгруппы, а не две
            # подряд. Без пометки студент читал «Физкультура / Иностранный»
            # как одно занятие с двумя предметами: чей предмет, чей
            # преподаватель и одновременно ли это — непонятно.
            if " / " in (lesson.subject or ""):
                lines.append("      <i>одновременно, по подгруппам</i>")

            # Что стояло раньше. Листок замен устроен как «было → стало»,
            # и раньше колонка «было» не сохранялась вовсе. Студент видел
            # новую пару со значком 🔄 и не знал, что она заменила.
            #
            # Печатаем, только если «было» действительно отличается от
            # «стало»: на проде 27 из 29 замен заменили ровно то же самое
            # (перенесли на другую дату), и строка «было: История - Куранова»
            # под «История · Куранова» только шумит.
            was = (getattr(lesson, "comment", "") or "").strip()
            if (was and getattr(lesson, "changed", False)
                    and not detail == DETAIL_BRIEF
                    and _was_differs(was, lesson)):
                lines.append(f"      <i>было: {_esc(was)}</i>")

            if lunch and lunch.para == p and (
                    detail == DETAIL_LUNCH
                    or (detail == DETAIL_FULL and lunch.position == "after")
            ):
                lines.append(_lunch_line(lunch))

    return "\n".join(lines)


def _esc(value) -> str:
    """Экранировать пользовательский текст перед вставкой в HTML.

    Бот шлёт всё с parse_mode=HTML, а предмет, преподаватель, кабинет и
    заметка приходят с сайта и из редактора. «Математика < 5» ломает
    отправку целиком: Telegram отвечает BadRequest, и экран дня не
    открывается ни у кого в группе.

    Экранируем на выводе, а не на записи: поиск по предмету и
    преподавателю идёт через LIKE, и «&lt;» в базе сломал бы его.
    """
    return escape(str(value)) if value is not None else ""


def day_header(date: datetime.date) -> str:
    """Единый заголовок дня для всех состояний."""
    return f"📅 <b>{WEEKDAY_FULL[date.weekday()]}, {date.day} {MONTHS_GEN[date.month]}</b>"


def _was_differs(was: str, lesson) -> bool:
    """Отличается ли «было» от того, что теперь показано.

    Листок замен пишет «было» строкой вида «История - Куранова Е.И.., ауд. 223»,
    а в слоте предмет и преподаватель лежат отдельно. Сравниваем по ним, без
    аудитории: аудитория меняется чаще всего и одна её разница — тоже повод
    показать строку. Двойная точка после инициалов встречается в листке.
    """
    head = was.split(", ауд.")[0]
    parts = head.split(" - ", 1)
    was_subj = _plain(parts[0])
    now_subj = _plain(getattr(lesson, "subject", "") or "")
    if was_subj and was_subj != now_subj:
        return True
    if len(parts) > 1:
        was_teach = _plain(parts[1])
        now_teach = _plain(getattr(lesson, "teacher", "") or "")
        if was_teach and was_teach != now_teach:
            return True
    return False


def _plain(text: str) -> str:
    """Для сравнения: без регистра, точек и лишних пробелов."""
    return re.sub(r"[\s.]+", " ", text or "").strip().casefold()


def empty_day(date: datetime.date, note: str | None = None) -> str:
    """Единая точка для состояния «пар нет».

    Используется и format_day (пустой список), и format_no_lessons,
    чтобы текст не расходился между вызовами.
    """
    text = f"{day_header(date)}\n\nЗанятий нет 🙌"
    if note:
        text += f"\n<i>{escape(note)}</i>"
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
    # `when` — время последнего УСПЕХА, а не начала сбоя. Прежняя
    # формулировка «не отвечает с 22:57» читалась наоборот: будто в
    # 22:57 всё сломалось, хотя именно тогда всё и получилось.
    return (f"\n\n⚠️ <i>Последняя успешная проверка замен — "
            f"{when:%d.%m в %H:%M}. С тех пор сайт не отвечал, "
            f"новые замены могли не попасть в расписание.</i>")


def format_unverified(date: datetime.date, when: datetime.datetime | None) -> str:
    """Пар нет, но и сайт недоступен — нельзя утверждать, что их нет.

    Отличается от format_no_lessons принципиально: там мы уверены, что
    занятий нет, здесь — просто не знаем.
    """
    return (f"{day_header(date)}\n\n"
            f"Занятий нет по постоянному расписанию 📋"
            f"{format_stale_warning(when)}")


def format_week(entries, bell, lunches, detail: str = DETAIL_BRIEF, meta: str = "teacher", show_rov: bool = True, group_course_group: dict[str, str] | None = None, merge_groups: bool = False) -> str:
    if not entries:
        return "На этой неделе расписания пока нет 📭"
    return "\n\n".join(
        format_day(d, les, bell, lunches, detail, meta, show_rov,
                   group_course_group, merge_groups=merge_groups)
        for d, les in entries)


def format_teacher_results(entries, bell, lunches, detail: str = DETAIL_BRIEF,
                           merge_groups: bool = False) -> str:
    parts = []
    for date, lessons in entries:
        parts.append(format_day(date, lessons, bell, lunches, detail, meta="group",
                                show_rov=False, merge_groups=merge_groups))
    return "\n\n".join(parts)


def format_bell(bell, lunches, vuz: bool = False) -> str:
    """Сетка звонков.

    У вуза своя: 8 пар до 22:00, без деления на курсы и без «Разговоров
    о важном». Раньше экран всегда показывал колледж, и преподаватель
    вуза видел чужую сетку с 5 парами.
    """
    if vuz:
        return _format_bell_vuz(bell, lunches)
    lines = ["⏰ <b>Расписание звонков</b>\n"]
    for day_type, title in [("MONDAY", "Понедельник"), ("OTHER", "Остальные дни")]:
        lines.append(f"<b>{title}</b>")
        rov = bell.get((day_type, "ALL", 0))
        if rov:
            lines.append(f"🇷🇺 Разговоры о важном · {rov.start:%H:%M}–{rov.end:%H:%M}")
        for cg, label in [("I_IV", "1 и 4 курс"), ("II_III", "2 и 3 курс")]:
            lunch = lunches.get((day_type, cg))
            paras = [bell[(day_type, cg, p)] for p in range(1, MAX_PARA + 1) if (day_type, cg, p) in bell]
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


def _format_bell_vuz(bell, lunches) -> str:
    """Звонки вуза: одна сетка на все дни, 8 пар."""
    lines = ["⏰ <b>Расписание звонков вуза</b>\n"]
    rows = [bell[(day_type, VUZ_GROUP, p)]
            for day_type in ("MONDAY", "OTHER")
            for p in range(1, 9)
            if (day_type, VUZ_GROUP, p) in bell]
    if not rows:
        lines.append("Сетка звонков вуза не загружена.")
        return "\n".join(lines)
    seen = set()
    for bs in rows:
        if bs.para in seen:
            continue
        seen.add(bs.para)
        lunch = lunches.get(("MONDAY", VUZ_GROUP))
        inline = lunch if (lunch and lunch.position == "inside" and lunch.para == bs.para) else None
        lines.append(f"{bs.para} пара  {_para_full(bs, inline)}")
    return "\n".join(lines)
