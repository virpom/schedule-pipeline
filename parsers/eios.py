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
# Хвостовые точки бывают лишними: «Балакшина О.П..», «Городиский В..»
_TEACHER_RE = re.compile(
    rf"^(?:{_NAME}(?:\s*[–-]\s*{_NAME})?\s+[А-ЯЁ]\.\s*[А-ЯЁ]?\.*"
    rf"|{_NAME}\s+{_NAME}|[Вв]акансия)$"
)
_TIME_HEAD_RE = re.compile(
    # В источнике оба префикса бывают сразу: «6-я пара с 18.05 до 19.40 - ».
    # Раньше они шли как «или-или», и такая строка проходила с непустым
    # хвостом — время оставалось в названии предмета.
    r"^\s*(?:\d+-я\s+пара(?:\s+с\s+\d+[.:]\d+\s+до\s*\.?[\d.:]+)?\s*-\s*"
    r"|с\s+\d+[.:]\d+\s+до\s*\.?[\d.:]+\s*-?\s*)",
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

        # Смысловые признаки раньше расширения. Раньше `endswith(".xlsx")`
        # стоял первым, и стоило колледжу переименовать листок замен в
        # .xlsx, как он попадал в «очную форму»: parse_ochoe вернул бы 0
        # пар, replace_base_lessons стёр бы 704 строки колледжа, а замены
        # не обновились бы вовсе — 220 студентов увидели «Занятий нет».
        if "замен" in name:
            result.zameny = url
        elif "заоч" in name:
            result.zaochnoe = url
        elif "звон" in url.lower() or "понед" in name or "стандарт" in name:
            if "понед" in name:
                result.bells_monday = url
            elif "стандарт" in name:
                result.bells_standard = url
        elif "консультац" in unquote(url).lower():
            # «Консультация преподавателей/Очная форма.xlsx» — другой файл
            # с тем же именем листа. Раньше проверка была только по имени
            # файла, и эта ссылка перетирала настоящее расписание: парсер
            # получал 17 строк консультаций, возвращал 0 пар, и синк
            # падал с «не найдено ни одной пары» каждые 5 минут.
            continue
        elif "очная" in name and name.endswith(".xlsx"):
            # Первая, а не последняя. Колледж уже один раз положил рядом
            # файл-двойник с тем же именем — тогда выиграла последняя
            # ссылка, и парсер разбирал консультации вместо расписания.
            # Настоящий файл всегда выше двойников на странице.
            result.ochoe = result.ochoe or url

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


def clean_teacher(name: str) -> str:
    """Убрать опечатки в ФИО: ``Балакшина О.П..`` → ``Балакшина О.П.``.

    В источнике встречаются лишние точки (``Городиский В..``,
    ``Кудрявцев С.И..``), а также ФИО без точки после инициала
    (``Борисенко А.Д``) — приводим к единому виду.
    """
    name = re.sub(r"\s+", " ", (name or "")).strip()
    if not name:
        return ""
    # «вакансия» и «Вакансия» — одна и та же пустая ставка. В файле
    # источник пишет по-разному, и в расписании 8 пар показывали
    # «вакансия» со строчной, а 54 — «Вакансия». Фильтр в списке
    # преподавателей (_clean_teacher_names) ловит оба варианта, но
    # карточка пары печатает поле как есть.
    if name.casefold() == "вакансия":
        return "Вакансия"
    # Инициалы: одна заглавная буква с точкой, допускаем опечатки.
    m = re.match(r"^(.+?)\s+([А-ЯЁ])\.?\s*([А-ЯЁ])?\.*$", name)
    if m:
        surname, first, second = m.group(1), m.group(2), m.group(3)
        return f"{surname} {first}.{second + '.' if second else ''}"
    return name


def split_subject_teacher(value: object) -> tuple[str, str]:
    """Разделить содержимое ячейки на предмет и преподавателя.

    Преподаватель — последняя строка (или хвост единственной строки).
    Предмет может занимать несколько строк.
    """
    subject, teacher = _split_subject_teacher(value)
    return subject, clean_teacher(teacher)


def _split_subject_teacher(value: object) -> tuple[str, str]:
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
    """Отрезать префикс времени вида «5-я пара - » или «с 18.00 до 21.00 - ».

    В источнике встречаются опечатки (``«с 18.05 до .19:30»``), поэтому
    убираем точку, ошибочно поставленную перед цифрой после «до».
    """
    m = _TIME_HEAD_RE.match(subject)
    if not m:
        return subject, None
    note = subject[: m.end()].strip(" -")
    note = re.sub(r"\bдо\s*\.(?=\d)", "до ", note)  # «до .19:30» -> «до 19:30»
    note = re.sub(r"\s+", " ", note).strip()
    return subject[m.end() :].strip(), note or None


# --- очное расписание --------------------------------------------------------


def _own_para(sheet, row: int, groups: dict[int, str]) -> int | None:
    """Номер пары, написанный в самой ячейке строки: «6-я пара с 18.05 …».

    Нужен для строк без номера в колонке B. Возвращает None, если ни в
    одной ячейке строки номера нет — тогда строку читать нечем.
    """
    for col in groups:
        value = sheet.cell(row, col).value
        if not value:
            continue
        match = re.match(r"\s*(\d+)-я\s+пара", str(value))
        if match:
            return int(match.group(1))
    return None


def parse_ochoe(data: bytes) -> list[BaseLesson]:
    """Разобрать «Очная форма.xlsx»."""
    try:
        workbook = openpyxl.load_workbook(BytesIO(data), data_only=True)
    except Exception as exc:  # noqa: BLE001
        raise EiosParseError(f"Не удалось открыть xlsx: {exc}") from exc

    lessons: list[BaseLesson] = []
    for sheet in workbook.worksheets:
        # Номер курса из имени листа («1 курс») в модель не пишется:
        # колонки course в base_lesson нет, а курс для звонков берётся
        # из группы (course_group_from_group). Считался и выбрасывался.

        groups: dict[int, str] = {}
        for col in range(3, sheet.max_column + 1):
            value = sheet.cell(3, col).value
            if value:
                groups[col] = str(value).strip()

        # Объединение по вертикали высотой 2 — «одна пара на обе недели».
        # Раньше условие было max_row == min_row + 1, то есть ровно две
        # строки. В файле встречаются объединения высотой 3 и 10-11
        # (шапки и колонка группы), а если методист склеит три строки под
        # пару, парсер молча потеряет данные: ячейка попадёт в обычную
        # ветку, верх прочтётся как чётная неделя, низ — как нечётная.
        # Берём любое вертикальное объединение, начинающееся в паре строк.
        merged_pairs = {
            (rng.min_row, rng.min_col)
            for rng in sheet.merged_cells.ranges
            if rng.min_col == rng.max_col and rng.max_row > rng.min_row
        }

        day: int | None = None
        for row in range(1, sheet.max_row + 1):
            head = sheet.cell(row, 1).value
            if head and str(head).strip().upper() in DAY_NAMES:
                day = DAY_NAMES[str(head).strip().upper()]

            para_cell = sheet.cell(row, 2).value
            if day is None:
                continue
            if para_cell and "пара" in str(para_cell):
                para_match = _PARA_RE.search(str(para_cell))
                if not para_match:
                    continue
                para = int(para_match.group())
            else:
                # Пара, дописанная ниже своего номера. Так бывает, когда
                # пара занимает три строки: в B стоит «5 пара» на объединении
                # B33:B35, а в C35 лежит «6-я пара с 18.05 до 19.40 - …» —
                # у неё свой номер прямо в тексте. Раньше строка 35
                # пропускалась целиком, потому что в B номера нет, и
                # шестая пара ТЭф-23 не попадала в базу вовсе.
                #
                # Номер берём ТОЛЬКО если он написан в самой ячейке.
                # Растянуть номер из B на все строки объединения — неверно:
                # строка 34 это вторая половина пятой пары, и она легла бы
                # поверх пятой.
                para = _own_para(sheet, row, groups)
                if para is None:
                    continue

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

    # Пустой разбор — ошибка, а не «ноль пар». Без этого сдвиг шапки
    # таблицы на одну строку вверх давал бы [] и replace_base_lessons
    # стёр бы все 704 пары колледжа молча, с записью в лог
    # «базовое расписание обновлено: 0 пар». Так же защищены
    # parse_substitutions и vuz.parse.
    if not lessons:
        raise EiosParseError(
            "В файле очного расписания не найдено ни одной пары — "
            "вероятно, изменилась структура листа"
        )
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
        return " – ".join(parts[:-1]).strip(), clean_teacher(parts[-1]), room
    return text, "", room


# --- звонки ------------------------------------------------------------------


_ROV_RE = re.compile(r"разговоры\s+о\s+важном", re.I)


def _is_razgovory(cells: list[str]) -> bool:
    """Строка «Разговоры о важном» — без номера пары, время в одной ячейке."""
    return bool(_ROV_RE.search(" ".join(cells)))


def _parse_range(text: str) -> tuple[datetime.time, datetime.time] | None:
    """«с 9.00 до 9.20 – «Разговоры…»» → (09:00, 09:20)."""
    found = _TIME_RE.findall(text or "")
    if len(found) < 2:
        return None
    start = datetime.time(int(found[0][0]), int(found[0][1]))
    end = datetime.time(int(found[1][0]), int(found[1][1]))
    return (start, end) if start < end else None


def parse_bells(data: bytes, day_type: str) -> list[BellSlot]:
    """Разобрать файл расписания звонков.

    Таблица ``14×7``: первая колонка — «N пара», далее по три колонки на
    поток («I и IV курс» и «II и III курс») в формате «начало | - | конец».

    Каждая пара занимает **две строки** (первая и вторая половина), между ними
    может стоять строка с обедом. Поэтому строки с обедом пропускаем, а пары
    собираем попарно.
    """
    try:
        document = Document(BytesIO(data))
    except Exception as exc:  # noqa: BLE001
        raise EiosParseError(f"Не удалось открыть docx звонков: {exc}") from exc

    slots: list[BellSlot] = []
    if not document.tables:
        return slots

    for table in document.tables:
        # para -> {"I_IV": [(start,end), ...], "II_III": [...]}
        halves: dict[int, dict[str, list[tuple[datetime.time, datetime.time]]]] = {}

        for row in table.rows:
            cells = [c.text.strip() for c in row.cells]
            if len(cells) < 7:
                continue
            m = re.match(r"\s*(\d)\s*пара", cells[0])
            if m:
                para = int(m.group(1))
            elif _is_razgovory(cells):
                # «Разговоры о важном» — единственная строка без номера
                # пары. Время лежит в одной ячейке («с 9.00 до 9.20»),
                # а не в двух, поэтому разбираем отдельно и кладём в
                # слот para=0 с course_group=ALL.
                times = _parse_range(cells[1])
                if times:
                    halves.setdefault(0, {}).setdefault("ALL", []).append(times)
                continue
            else:
                continue

            for group_key, offset in (("I_IV", 1), ("II_III", 4)):
                start_cell, end_cell = cells[offset], cells[offset + 2]
                # Строка обеда тоже содержит время — её надо пропустить.
                if "обед" in start_cell.lower() or "обед" in end_cell.lower():
                    continue
                start = parse_time(start_cell)
                end = parse_time(end_cell)
                if start and end:
                    halves.setdefault(para, {}).setdefault(group_key, []).append((start, end))

        for para, per_group in sorted(halves.items()):
            for group_key, pairs in per_group.items():
                if len(pairs) >= 2:
                    (s1, e1), (s2, e2) = pairs[0], pairs[1]
                else:
                    # одна половина — считаем её единственной
                    (s1, e1) = pairs[0]
                    s2, e2 = s1, e1
                slots.append(
                    BellSlot(
                        day_type=day_type,
                        course_group=group_key,
                        para=para,
                        start=s1,
                        end1=e1,
                        start2=s2,
                        end2=e2,
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

# Опечатки, подтверждённые на реальных данных (см. docs/SOURCE-EIOS.md).
# Ключ — «грязное» имя из листка замен, значение — настоящее имя группы.
KNOWN_TYPOS: dict[str, str] = {
    # В листке замен 26.10.2026 стояло «ЭОф-26». Такой группы нет ни на одном
    # курсе; замена ссылается на «ОБиЗР – Боровик И.А.», а это единственная
    # группа 1 курса с этим предметом и преподавателем в понедельник 4 парой.
    # Плюс «ЭОф-NN» — шаблон 2–4 курсов, у 1 курса суффикс стоит в середине
    # («ЭО-26ФП»).
    "ЭОФ26": "ЭО-26ФП",
}


def normalize_group(name: str) -> str:
    """Привести имя группы к сравнимому виду.

    Колледж пишет одну и ту же группу по-разному: ``ЭОК-26`` / ``ЭОк-26``,
    ``ДОУ - 25`` / ``ДОУ-25``.
    """
    return re.sub(r"[\s\-]", "", (name or "")).upper()


def match_group(name: str, known: list[str]) -> str | None:
    """Найти известную группу по «грязному» имени из листка замен.

    Порядок: точное совпадение → таблица известных опечаток → нечёткая
    похожесть. Если похожих несколько и они равны — не угадываем.
    """
    key = normalize_group(name)
    by_key = {normalize_group(g): g for g in known}
    if key in by_key:
        return by_key[key]

    # Подтверждённые опечатки.
    fixed = KNOWN_TYPOS.get(key)
    if fixed and normalize_group(fixed) in by_key:
        return by_key[normalize_group(fixed)]

    # Похожесть: те же символы в другом порядке либо одно вхождение в другое.
    candidates: list[tuple[float, str]] = []
    for other_key, original in by_key.items():
        # Анаграмма НЕ считается точным совпадением: набор символов
        # совпадает у двух разных вещей. «26ДП» — та же группа с
        # перепутанным порядком букв и цифр. «ПД-26» — другая
        # специальность.
        #
        # Отличаем по позициям цифр: у перепутанной группы номер стоит не
        # там, где в базе, а у чужой специальности буквы меняются местами
        # внутри своего блока, и цифры остаются на своих позициях.
        if sorted(key) == sorted(other_key):
            if _digit_slots(key) == _digit_slots(other_key):
                continue            # «ПД26» и «ДП26» — разные группы
            score = 1.0             # «26ДП» и «ДП26» — та же, перепутан номер
        elif key in other_key or other_key in key:
            score = 0.9
        else:
            score = _similarity(key, other_key)
            if score < 0.75:
                continue
        candidates.append((score, original))

    if not candidates:
        return None
    candidates.sort(reverse=True)
    # Если два кандидата одинаково хороши — не угадываем.
    if len(candidates) > 1 and abs(candidates[0][0] - candidates[1][0]) < 0.05:
        return None
    return candidates[0][1]


def _digits(text: str) -> str:
    return "".join(ch for ch in text if ch.isdigit())


def _digit_slots(text: str) -> tuple[int, ...]:
    """Позиции цифр в строке: у «ДП26» это (2, 3), у «26ДП» — (0, 1)."""
    return tuple(i for i, ch in enumerate(text) if ch.isdigit())


def _similarity(a: str, b: str) -> float:
    from difflib import SequenceMatcher

    return SequenceMatcher(None, a, b).ratio()
