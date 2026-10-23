"""Парсер расписания СПО с ЭИОС (eios.norvuz.ru).

Источник — страница Moodle «Расписание занятий» (id=49960), блок
«Политехнический колледж». Оттуда берутся три файла:

* ``СПО/Очная форма.xlsx``     — базовое расписание на семестр
* ``СПО/Листок замен.docx``    — замены по конкретным датам
* ``Расписание звонков/*.docx`` — время пар

Подробное описание формата — в ``docs/SOURCE-EIOS.md``.

Ключевая особенность xlsx: пара занимает две строки. Если ячейка объединена
(merge) — это одна пара на обе недели. Если нет — верхняя строка относится к
чётной неделе, нижняя к нечётной.
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, field
from io import BytesIO
from urllib.parse import unquote, urljoin

import openpyxl
from bs4 import BeautifulSoup
from docx import Document
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

# --- константы ---------------------------------------------------------------

PAGE_URL = "https://eios.norvuz.ru/mod/page/view.php?id=49960"
LINK_MARKER = "timetable.ptk"

PARITY_EVEN = "EVEN"
PARITY_ODD = "ODD"
PARITY_BOTH = "BOTH"

SUB_REPLACE = "replace"
SUB_CANCEL = "cancel"
SUB_ADD = "add"

DAY_NAMES = {
    "ПОНЕДЕЛЬНИК": 1,
    "ВТОРНИК": 2,
    "СРЕДА": 3,
    "ЧЕТВЕРГ": 4,
    "ПЯТНИЦА": 5,
    "СУББОТА": 6,
}

_NAME = r"[А-ЯЁ][а-яё\-]+"
_TEACHER_RE = re.compile(
    rf"^(?:{_NAME}(?:\s*[–-]\s*{_NAME})?\s+[А-ЯЁ]\.\s*[А-ЯЁ]?\.?"
    rf"|{_NAME}\s+{_NAME}|[Вв]акансия)$"
)
_TIME_HEAD_RE = re.compile(
    r"^\s*(?:\d+-я\s+пара\s*-\s*|с\s+\d+[.:]\d+\s+до\s*\.?[\d.:]+\s*-?\s*)",
    re.IGNORECASE,
)
_TIME_TAIL_RE = re.compile(rf"\s+({_NAME}\s+[А-ЯЁ]\.\s*[А-ЯЁ]?\.?)\s*$")
_VACANCY_TAIL_RE = re.compile(r"\s+([Вв]акансия)$")
_PARA_RE = re.compile(r"\d+")
_DAY_HEADER_RE = re.compile(
    r"на\s+(\d{2})\.(\d{2})\.(\d{4}),\s*([^,]+),\s*(\S+)\s+неделя", re.IGNORECASE
)
_SUBJECT_TEACHER_SEP = re.compile(r"\s+[–—-]\s+")


class EiosParseError(RuntimeError):
    """Структура источника не та, что мы ожидаем."""


# --- модели ------------------------------------------------------------------


@dataclass(slots=True)
class BaseLesson:
    """Пара из базового расписания."""

    group: str
    course: int | None
    day: int  # 1..6
    para: int  # 1..6
    subject: str
    teacher: str
    parity: str = PARITY_BOTH  # EVEN | ODD | BOTH
    time_note: str | None = None


@dataclass(slots=True)
class Substitution:
    """Замена на конкретную дату."""

    date: datetime.date
    group: str
    para: int
    action: str  # replace | cancel | add
    was: str = ""  # что стояло в расписании (как написано в листке)
    subject: str = ""  # новый предмет
    teacher: str = ""
    room: str = ""
    raw_now: str = ""
    weekday: str = ""
    parity: str = ""  # чётность, как её назвал колледж


@dataclass(slots=True)
class BellSlot:
    day_type: str  # MONDAY | OTHER
    course_group: str  # I_IV | II_III
    para: int
    start: datetime.time
    end1: datetime.time
    start2: datetime.time
    end2: datetime.time


@dataclass(slots=True)
class SourceLinks:
    """Ссылки, вытащенные со страницы."""

    ochoe: str | None = None
    zaochnoe: str | None = None
    zameny: str | None = None
    bells_monday: str | None = None
    bells_standard: str | None = None
    all_links: dict[str, str] = field(default_factory=dict)


# --- извлечение ссылок -------------------------------------------------------


def extract_links(html: str, base_url: str = PAGE_URL) -> SourceLinks:
    """Достать ссылки на файлы СПО со страницы расписания."""
    soup = BeautifulSoup(html, "html.parser")
    result = SourceLinks()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if LINK_MARKER not in href:
            continue
        url = urljoin(base_url, href)
        name = unquote(url.split("?")[0].split("#")[0].rsplit("/", 1)[-1]).lower()
        result.all_links[name] = url

        if name.endswith(".xlsx"):
            result.ochoe = url
        elif "замен" in name:
            result.zameny = url
        elif "заоч" in name:
            result.zaochnoe = url
        elif "звон" in url.lower() or "понед" in name or "стандарт" in name:
            if "понед" in name:
                result.bells_monday = url
            elif "стандарт" in name:
                result.bells_standard = url

    if not result.ochoe:
        raise EiosParseError(
            "На странице не найдена ссылка на «Очная форма.xlsx» — "
            "структура источника изменилась"
        )
    return result


# --- разбор текста ячейки ----------------------------------------------------


def _lines(value: object) -> list[str]:
    if not value:
        return []
    return [re.sub(r"\s+", " ", part).strip() for part in str(value).split("\n") if part.strip()]


def split_subject_teacher(value: object) -> tuple[str, str]:
    """Разделить содержимое ячейки на предмет и преподавателя.

    Преподаватель — последняя строка (или хвост единственной строки).
    Предмет может занимать несколько строк.
    """
    lines = _lines(value)
    if not lines:
        return "", ""

    if len(lines) == 1:
        text = lines[0]
        m = _VACANCY_TAIL_RE.search(text)
        if m:
            return text[: m.start()].strip(), m.group(1)
        m = _TIME_TAIL_RE.search(text)
        if m and len(text[: m.start()].strip()) > 3:
            return text[: m.start()].strip(), m.group(1)
        return text, ""

    if _TEACHER_RE.match(lines[-1]):
        return " ".join(lines[:-1]), lines[-1]

    joined = " ".join(lines)
    m = _TIME_TAIL_RE.search(joined)
    if m and len(joined[: m.start()].strip()) > 3:
        return joined[: m.start()].strip(), m.group(1)
    return joined, ""


def _strip_time_note(subject: str) -> tuple[str, str | None]:
    """Отрезать префикс времени вида «5-я пара - » или «с 18.00 до 21.00 - »."""
    m = _TIME_HEAD_RE.match(subject)
    if not m:
        return subject, None
    note = subject[: m.end()].strip(" -")
    return subject[m.end() :].strip(), note or None


# --- очное расписание --------------------------------------------------------


def parse_ochoe(data: bytes) -> list[BaseLesson]:
    """Разобрать «Очная форма.xlsx»."""
    try:
        workbook = openpyxl.load_workbook(BytesIO(data), data_only=True)
    except Exception as exc:  # noqa: BLE001
        raise EiosParseError(f"Не удалось открыть xlsx: {exc}") from exc

    lessons: list[BaseLesson] = []
    for sheet in workbook.worksheets:
        course_match = re.search(r"\d", sheet.title)
        course = int(course_match.group()) if course_match else None

        groups: dict[int, str] = {}
        for col in range(3, sheet.max_column + 1):
            value = sheet.cell(3, col).value
            if value:
                groups[col] = str(value).strip()

        merged_pairs = {
            (rng.min_row, rng.min_col)
            for rng in sheet.merged_cells.ranges
            if rng.min_col == rng.max_col and rng.max_row == rng.min_row + 1
        }

        day: int | None = None
        for row in range(1, sheet.max_row + 1):
            head = sheet.cell(row, 1).value
            if head and str(head).strip().upper() in DAY_NAMES:
                day = DAY_NAMES[str(head).strip().upper()]

            para_cell = sheet.cell(row, 2).value
            if not (para_cell and "пара" in str(para_cell)):
                continue
            para_match = _PARA_RE.search(str(para_cell))
            if not para_match or day is None:
                continue
            para = int(para_match.group())

            for col, group in groups.items():
                top = sheet.cell(row, col).value
                bottom = (
                    sheet.cell(row + 1, col).value if row + 1 <= sheet.max_row else None
                )
                top_subject, top_teacher = split_subject_teacher(top)
                bot_subject, bot_teacher = split_subject_teacher(bottom)
                bottom_lines = _lines(bottom)

                # Продолжение предмета: снизу только ФИО.
                if (
                    (row, col) not in merged_pairs
                    and bottom
                    and len(bottom_lines) == 1
                    and _TEACHER_RE.match(bottom_lines[0])
                    and top_subject
                    and not top_teacher
                ):
                    lessons.append(
                        BaseLesson(
                            group=group,
                            course=course,
                            day=day,
                            para=para,
                            subject=top_subject,
                            teacher=bottom_lines[0],
                        )
                    )
                    continue

                # Объединённая ячейка — одна пара на обе недели.
                if (row, col) in merged_pairs:
                    if top_subject:
                        lessons.append(
                            BaseLesson(
                                group=group,
                                course=course,
                                day=day,
                                para=para,
                                subject=top_subject,
                                teacher=top_teacher,
                            )
                        )
                    continue

                # Разъединённая: верх = чётная, низ = нечётная.
                if top_subject:
                    lessons.append(
                        BaseLesson(
                            group=group,
                            course=course,
                            day=day,
                            para=para,
                            subject=top_subject,
                            teacher=top_teacher,
                            parity=PARITY_EVEN,
                        )
                    )
                if bot_subject:
                    lessons.append(
                        BaseLesson(
                            group=group,
                            course=course,
                            day=day,
                            para=para,
                            subject=bot_subject,
                            teacher=bot_teacher,
                            parity=PARITY_ODD,
                        )
                    )

    # Вынести время из предмета.
    for lesson in lessons:
        lesson.subject, lesson.time_note = _strip_time_note(lesson.subject)
        if not lesson.teacher:
            m = _TIME_TAIL_RE.search(lesson.subject)
            if m:
                lesson.teacher = m.group(1)
                lesson.subject = lesson.subject[: m.start()].strip()

    return lessons


# --- листок замен ------------------------------------------------------------


def parse_substitutions(data: bytes) -> list[Substitution]:
    """Разобрать «Листок замен.docx».

    Заголовок дня («на 24.10.2026, суббота, четная неделя») идёт перед своей
    таблицей, поэтому обходим тело документа по порядку.
    """
    try:
        document = Document(BytesIO(data))
    except Exception as exc:  # noqa: BLE001
        raise EiosParseError(f"Не удалось открыть docx: {exc}") from exc

    blocks: list[tuple[datetime.date, str, str, int]] = []
    current: tuple[datetime.date, str, str] | None = None
    table_index = 0

    for child in document.element.body.iterchildren():
        if child.tag == qn("w:p"):
            text = Paragraph(child, document).text.strip()
            m = _DAY_HEADER_RE.search(text)
            if m:
                day, month, year, weekday, parity_word = m.groups()
                parity = PARITY_EVEN if parity_word.lower().startswith("чет") else PARITY_ODD
                current = (
                    datetime.date(int(year), int(month), int(day)),
                    weekday.strip(),
                    parity,
                )
        elif child.tag == qn("w:tbl"):
            if current and table_index < len(document.tables):
                blocks.append((*current, table_index))
            table_index += 1

    if not blocks:
        raise EiosParseError("В листке замен не найдено ни одного заголовка с датой")

    result: list[Substitution] = []
    for date, weekday, parity, idx in blocks:
        table = document.tables[idx]
        for row in table.rows[1:]:
            cells = [c.text.strip() for c in row.cells]
            if len(cells) < 4 or not cells[0]:
                continue
            group, para_text, was, now = cells[0], cells[1], cells[2], cells[3]
            paras = [int(d) for d in re.findall(r"\d", para_text)]
            if not paras:
                continue

            if now.upper().startswith("НЕТ ПАРЫ"):
                action = SUB_CANCEL
                subject = teacher = room = ""
            else:
                action = SUB_ADD if was.upper().strip() == "НЕТ" else SUB_REPLACE
                subject, teacher, room = split_substitution_text(now)

            for para in paras:
                result.append(
                    Substitution(
                        date=date,
                        group=group,
                        para=para,
                        action=action,
                        was=was,
                        subject=subject,
                        teacher=teacher,
                        room=room,
                        raw_now=now,
                        weekday=weekday,
                        parity=parity,
                    )
                )

    return result


_ROOM_RE = re.compile(
    r",\s*(ауд\.?\s*[\w\-/]+|спортзал\w*|актовый зал|см\.?\s*р\.?|мастерск\w*)\s*$",
    re.IGNORECASE,
)


def split_substitution_text(text: str) -> tuple[str, str, str]:
    """Разобрать «Чем заменяется»: предмет, преподаватель, аудитория.

    ``Биология – Утева О.В., ауд. 202`` → (``Биология``, ``Утева О.В.``, ``ауд. 202``)
    """
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        return "", "", ""

    room = ""
    m = _ROOM_RE.search(text)
    if m:
        room = m.group(1).strip()
        text = text[: m.start()].strip()

    parts = _SUBJECT_TEACHER_SEP.split(text)
    if len(parts) >= 2 and _TEACHER_RE.match(parts[-1]):
        return " – ".join(parts[:-1]).strip(), parts[-1].strip(), room
    return text, "", room


# --- звонки ------------------------------------------------------------------


def parse_bells(data: bytes, day_type: str) -> list[BellSlot]:
    """Разобрать файл расписания звонков.

    Таблица: первая колонка — номер пары, далее пары колонок
    «I и IV курс» и «II и III курс» (начало / конец).
    """
    try:
        document = Document(BytesIO(data))
    except Exception as exc:  # noqa: BLE001
        raise EiosParseError(f"Не удалось открыть docx звонков: {exc}") from exc

    slots: list[BellSlot] = []
    if not document.tables:
        return slots

    for table in document.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells]
            if len(cells) < 5:
                continue
            para_match = re.fullmatch(r"\s*(\d)\s*", cells[0])
            if not para_match:
                continue
            para = int(para_match.group(1))
            times = [parse_time(c) for c in cells[1:]]
            if len(times) < 4 or not all(times[:4]):
                continue
            slots.append(
                BellSlot(
                    day_type=day_type,
                    course_group="I_IV",
                    para=para,
                    start=times[0],
                    end1=times[1],
                    start2=times[2],
                    end2=times[3],
                )
            )
            if len(times) >= 8 and times[4] and times[5] and times[6] and times[7]:
                slots.append(
                    BellSlot(
                        day_type=day_type,
                        course_group="II_III",
                        para=para,
                        start=times[4],
                        end1=times[5],
                        start2=times[6],
                        end2=times[7],
                    )
                )
    return slots


_TIME_RE = re.compile(r"(\d{1,2})[.:](\d{2})")


def parse_time(text: str) -> datetime.time | None:
    m = _TIME_RE.search(text or "")
    if not m:
        return None
    hour, minute = int(m.group(1)), int(m.group(2))
    if hour > 23 or minute > 59:
        return None
    return datetime.time(hour, minute)


# --- нормализация групп ------------------------------------------------------


def normalize_group(name: str) -> str:
    """Привести имя группы к сравнимому виду.

    Колледж пишет одну и ту же группу по-разному: ``ЭОК-26`` / ``ЭОк-26``,
    ``ДОУ - 25`` / ``ДОУ-25``.
    """
    return re.sub(r"[\s\-]", "", (name or "")).upper()


def match_group(name: str, known: list[str]) -> str | None:
    """Найти известную группу по «грязному» имени из листка замен."""
    key = normalize_group(name)
    by_key = {normalize_group(g): g for g in known}
    if key in by_key:
        return by_key[key]
    return None
