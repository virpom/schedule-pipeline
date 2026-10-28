"""Парсер расписания ВУЗа (ЗГУ) из файлов `.xls` на norvuz.ru.

Источник — `https://norvuz.ru/upload/timetable/`:

* ``1-ochnoe.xls``        — бакалавриат/специалитет, очная
* ``2-ochno-zaochnoe.xls`` — бакалавриат/специалитет, очно-заочная
* ``3-zaochnoe.xls``      — заочная (пока не берём)

Формат — BIFF (`.xls`), поэтому читается через ``xlrd``, а не ``openpyxl``.
``formatting_info=True`` обязателен: без него не видно объединённых ячеек,
а на них держится половина структуры.

Устройство листа (проверено на реальных файлах):

* строка 5 — название факультета;
* строка 6 — «N КУРС M СЕМЕСТР»;
* строка 7 — шапка: день, время, дальше пары «группа / ауд»;
* день недели — в колонке 0, объединён по блоку;
* время — **не всегда в одной колонке**: в листе «ФЭЭиУ 1 курс» оно
  в колонке 2 (в 1 лежат реальные часы занятий), у остальных в колонке 1;
* пара занимает **две строки**: верхняя — нечётная неделя, нижняя — чётная;
  если ячейка объединена по вертикали, пара идёт обе недели;
* чётность может быть задана тремя способами: префиксом ``н.``/``ч.``,
  объединением ячеек или списком недель ``№н. 5-13`` (здесь ``№н`` —
  **номер недели**, а не «нечётная»).

Подробный разбор источника — ``docs/VUZ.md``.
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, field
import xlrd

# --- константы ---------------------------------------------------------------

BASE_URL = "https://norvuz.ru/upload/timetable"

PARITY_ODD = "ODD"
PARITY_EVEN = "EVEN"
PARITY_ANY = "ANY"

SUB_REPLACE = "replace"
SUB_CANCEL = "cancel"
SUB_ADD = "add"

VUZ_SUFFIX = "@vuz"

# Сетка вуза: восемь пар. Ключ — нормализованное время без пробелов.
GRID = {
    "8.40-10.10": 1, "10.20-11.50": 2, "12.10-13.40": 3, "13.50-15.20": 4,
    "15.30-17.00": 5, "17.10-18.40": 6, "18.50-20.20": 7, "20.30-22.00": 8,
    "8:40-10:10": 1, "10:20-11:50": 2, "12:10-13:40": 3, "13:50-15:20": 4,
    "15:30-17:00": 5, "17:10-18:40": 6, "18:50-20:20": 7, "20:30-22:00": 8,
}

DAY_RE = re.compile(
    r"^(понедельник|вторник|среда|четверг|пятница|суббота|воскресенье)$", re.I)
TIME_RE = re.compile(r"^\s*\d{1,2}[.:]\d{2}\s*[-–]\s*\d{1,2}[.:]\d{2}\s*$")
# Пометка чётности: «н.», «ч.» с точкой. Точка обязательна — без неё
# регулярка съедает первую букву названия («Неорганическая» -> «еорганическая»).
PARITY_RE = re.compile(r"^\s*(н|ч)\s*\.", re.I)
# Одинокая «ч» без точки тоже встречается как пометка чётности.
LONE_PARITY_RE = re.compile(r"^\s*[нч]\s*$", re.I)
# «№н. 5-13», «№н.5,7,9», «№нед. 9-12» — это номера недель.
# Два порядка написания: «№н. 5-13» и «нед. № 10». Второй вуз пишет для
# пар, начинающихся с середины семестра; раньше он не разбирался вовсе, и
# такая пара показывалась на всех неделях вместо «с 10-й».
# Список цифр расписан явно, а не классом [\d\s,;\-–]: дефис-разделитель
# попадал в класс, parse_week_list видел «10 - » и не разбирал ничего.
WEEK_LIST_RE = re.compile(
    r"(?:№\s*(?:нед\.?|н\.?)|(?:нед\.?|н\.)\s*№)\s*"
    r"(\d+(?:\s*[-–]\s*\d+)?(?:\s*[,;]\s*\d+(?:\s*[-–]\s*\d+)?)*)",
    re.I)
# Дата в ячейке: 26.10.2026, 09.11.2026. — признак переноса/замены.
DATE_RE = re.compile(r"(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?")
# «перенос на 13.50», «замена», «отмена» — пометки о движении пары.
MOVE_RE = re.compile(r"перенос|замен|отмен", re.I)
# Время начала внутри ячейки: «с 18.50 - Металлургия». Такая пара стоит
# не в своём блоке, а позже — номер пары надо брать из этого времени.
# «с 18.50 - X», «с 15.30.-17.00 X», «с 15.30-17.00X» — берём время
# начала и, если есть, конец диапазона.
INLINE_TIME_RE = re.compile(
    r"^\s*с[\s.]*(\d{1,2})[.:](\d{2})"
    r"(?:\s*[.\-–—]*\s*\d{1,2}[.:]\d{2})?", re.I)

# Служебные подписи в шапке — не группы.
SERVICE = {"день недели", "дни", "время", "часы", "ауд", "аудитория", "пара"}


class VuzParseError(RuntimeError):
    """Файл не похож на расписание вуза — вероятно, сменилась структура."""


@dataclass
class VuzLesson:
    group: str          # с суффиксом @vuz
    weekday: int        # 1..7
    para: int
    parity: str         # ODD | EVEN | ANY
    subject: str
    teacher: str = ""
    room: str = ""
    weeks: tuple[int, ...] = ()   # конкретные номера недель, если заданы списком
    date: datetime.date | None = None   # для датированных клеток


@dataclass
class VuzGroup:
    name: str           # с суффиксом
    faculty: str        # FEU | GTF
    course: int
    form: str           # full | part | extramural


@dataclass
class VuzChange:
    """Перенос или замена на конкретную дату внутри файла расписания."""
    group: str
    date: datetime.date
    para: int | None
    subject: str
    teacher: str = ""
    room: str = ""
    action: str = SUB_REPLACE   # replace | cancel | add


@dataclass
class VuzSheet:
    lessons: list[VuzLesson]
    groups: list[VuzGroup]
    changes: list[VuzChange] = field(default_factory=list)


# --- разбор ячеек ------------------------------------------------------------

def normalize_time(value: str) -> str:
    """Привести метку времени к виду из GRID: без пробелов, через дефис."""
    t = str(value).strip().replace("–", "-").replace("—", "-")
    t = re.sub(r"\s+", "", t)
    # «8.40-10.10» и «8:40-10:10» — одно и то же
    return t


def para_from_time(value: str) -> int | None:
    t = normalize_time(value)
    if t in GRID:
        return GRID[t]
    # Опечатки вроде «18.50 - 22.00»: ищем по началу.
    head = t.split("-")[0]
    for key, para in GRID.items():
        if key.split("-")[0] == head:
            return para
    return None


def parse_week_list(text: str) -> tuple[int, ...]:
    """Развернуть «5-13» или «5,7,9» в кортеж номеров недель."""
    numbers: list[int] = []
    for chunk in re.split(r"[,;]", text):
        chunk = chunk.strip()
        if not chunk:
            continue
        m = re.match(r"^(\d+)\s*[-–]\s*(\d+)$", chunk)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            # См. ниже: верхняя граница недели — 60.
            # Неделя — 1..60 (см. разбор одиночного числа ниже). Проверка
            # b - a < 40 от «2026-2027» не спасала: разница 1. Год учебного
            # года, приписанный к списку, давал weeks=(2026, 2027) и пара
            # показывалась в чужие недели.
            if a <= b and b <= 60:
                numbers.extend(range(a, b + 1))
            continue
        m = re.match(r"^\d+$", chunk)
        if m:
            n = int(chunk)
            # В файле встречается опечатка «6,8,10,1218» вместо «12,18».
            # Число больше 60 неделей быть не может — разбиваем на пары.
            # Верхняя граница 9999: «1218» — склейка двух двузначных,
            # а «20262027» — год; разделяем по длине, а не по величине.
            if 60 < n <= 9999 and len(chunk) % 2 == 0:
                numbers.extend(n2 for n2 in (int(chunk[i:i + 2])
                                             for i in range(0, len(chunk), 2))
                               if 1 <= n2 <= 60)
            elif 1 <= n <= 60:
                numbers.append(n)
    return tuple(sorted(set(numbers)))


# ФИО: «Самойлова Л. П.», «Левочкина Н.А.», «Фаддеенков А.В.»
# Инициалы бывают с точками и без, с пробелом и без:
# «Самойлова Л. П.», «Левочкина Н.А.», «Андреева Н.В».
# Фамилия бывает двойной: «Мурашова-Росс А.В.» — вторая часть с заглавной.
# Фамилия бывает двойной («Мурашова-Росс»), с лишней точкой после неё
# («Каверзин. А.В») или слипшейся с инициалами («ВостриковК.В»).
TEACHER_RE = re.compile(
    r"([А-ЯЁ][а-яё]*(?:-[А-ЯЁ]?[а-яё]+)*\.?"
    r"(?:\s*[А-ЯЁ]\.[\s]*[А-ЯЁ]\.?)?)")


def split_teacher(text: str) -> tuple[str, str]:
    """Разделить «Предмет (лек. №н.5-13) Иванов И.И.» на предмет и ФИО.

    ФИО может стоять не в конце: после него в ячейке бывает дата и
    пометка о переносе. Поэтому ищем первое совпадение с образцом
    «Фамилия И.О.», а не последнее слово.
    """
    text = re.sub(r"\s+", " ", str(text)).strip()
    if not text:
        return "", ""
    best = None
    for m in TEACHER_RE.finditer(text):
        if "." not in m.group(1):
            continue          # нужны инициалы, иначе это просто слово
        if not re.search(r"[А-ЯЁ]\.", m.group(1)):
            continue
        if len(m.group(1)) > 4:
            best = m
            break
    if best:
        subject = text[: best.start()].strip(" ,;")
        teacher = best.group(1).strip()
        if subject:
            return subject, teacher
    return text, ""


def inline_para(text: str) -> tuple[int | None, str]:
    """Номер пары из времени в начале ячейки и текст без этого времени.

    В листе «ГТФ 4 курс» в блоке 13.50-15.20 стоят ячейки «с 18.50 - ...»
    и «с 20.30 - ...»: это 7-я и 8-я пары, а не 4-я.
    """
    # Префикс чётности может стоять перед временем: «н. с 15.30 - ...».
    stripped = PARITY_RE.sub("", text).lstrip() if PARITY_RE.match(text) else text
    m = INLINE_TIME_RE.match(stripped)
    if not m:
        return None, text
    head = f"{int(m.group(1))}.{m.group(2)}"
    for key, para in GRID.items():
        if key.split("-")[0] == head:
            rest = stripped[m.end():].lstrip(" .-–—")
            return para, rest
    # Время не из сетки («с 18.30» — 7-я пара со сдвигом на 20 минут).
    # Номер пары неизвестен, но время из названия убрать надо: иначе
    # оно висит в предмете, а пара встаёт в слот, который дал ряд.
    # ponytail: без сдвига времени, только очистка названия; если
    # сдвинутых пар станет много — добавлять их в GRID.
    return None, stripped[m.end():].lstrip(" .-–—")


def split_by_weeks(text: str) -> list[str]:
    """Разбить ячейку на части, у каждой из которых свой список недель.

    «Страхование (лек. №н. 1-7) Юрченко А.А.; (лек. №н. 8-18) Носкова Е.М.»
    — один предмет, два преподавателя на разных неделях. Такие части
    разделены точкой с запятой. Если список недель в ячейке один,
    делить нечего — возвращаем текст целиком.
    """
    parts = [p.strip() for p in text.split(";") if p.strip()]
    with_weeks = [p for p in parts if WEEK_LIST_RE.search(p)]
    if len(parts) > 1 and len(with_weeks) > 1:
        return with_weeks
    return [text]


def parse_date(text: str, year: int) -> datetime.date | None:
    """Дата из ячейки: «09.11.2026» или «26.10» (год по умолчанию)."""
    for m in DATE_RE.finditer(text):
        day, month = int(m.group(1)), int(m.group(2))
        y = int(m.group(3)) if m.group(3) else year
        if y < 100:
            y += 2000
        try:
            return datetime.date(y, month, day)
        except ValueError:
            continue
    return None


def is_move(text: str) -> bool:
    """Ячейка привязана к дате, а не к неделе семестра.

    Вуз не выкладывает листок замен отдельно: замена или перенос стоят
    прямо в клетке расписания с датой. Признак — дата в тексте, а не
    слово «перенос»: бывает «03.11.2026 - Неорганическая химия» без
    пояснений, и это всё равно разовая пара на дату.
    """
    # Время в начале ячейки («с 18.50 - ...») DATE_RE принимал за дату
    # 18-го числа 50-го месяца, и вся пара выбрасывалась как перенос:
    # две замены вуза висели в базе с временем в названии предмета.
    # Время — это номер пары, а не дата, поэтому проверяем его первым.
    if INLINE_TIME_RE.match(text):
        return bool(MOVE_RE.search(text))
    return bool(DATE_RE.search(text) or MOVE_RE.search(text))


def unspace(text: str) -> str:
    """Убрать разрядку: «О с н о в ы   р о с с и й с к о й» -> «Основы российской».

    В файлах вуза часть названий набрана с пробелом между каждой буквой —
    похоже, побочный эффект выравнивания по ширине. Границы слов видны
    по двойным пробелам, одиночные — это разрядка внутри слова.
    """
    words = text.split()
    if len(words) < 4:
        return text
    single = sum(1 for w in words if len(w) == 1 and w.isalpha())
    if single < len(words) * 0.4:
        return text

    # Слово кончается там, где после буквы идёт 2+ пробела.
    parts = re.split(r"\s{2,}", text.strip())
    result = []
    for part in parts:
        letters = part.split()
        if letters and all(len(w) == 1 and w.isalpha() for w in letters):
            result.append("".join(letters))
        else:
            # Смешанная часть: склеиваем только одиночные буквы подряд.
            merged, buf = [], ""
            for word in letters:
                if len(word) == 1 and word.isalpha():
                    buf += word
                    continue
                if buf:
                    merged.append(buf)
                    buf = ""
                merged.append(word)
            if buf:
                merged.append(buf)
            result.append(" ".join(merged))
    return " ".join(result)


def clean_subject(text: str) -> str:
    """Убрать служебные пометки: префикс чётности, номер недели, дату.

    Ячейка с одиноким ``н.`` или ``ч.`` означает «на этой неделе пары
    нет» — после чистки получается пустая строка, и пара не создаётся.
    """
    t = unspace(str(text))
    t = re.sub(r"\s+", " ", t).strip()
    t = PARITY_RE.sub("", t).strip()
    if LONE_PARITY_RE.match(t):
        return ""
    t = WEEK_LIST_RE.sub("", t).strip(" ,;")
    # От «С нед. № 10 - » остаётся «С - »: снимаем хвост, оставшийся от
    # пометки недели, иначе он попадает в название предмета и ломает
    # поиск по названию.
    t = re.sub(r"^\s*[сc]?\s*[-–—]\s*", "", t, flags=re.I)
    t = re.sub(r"^[\s.,;]+", "", t)
    # Дата и пометка о переносе — не часть названия: «09.11.2026 - Основы...».
    # Дат бывает несколько подряд: «14, 28.11; 12.12.2026 - Химия».
    # Дат в начале бывает несколько: «14, 28.11; 12.12.2026 - Химия».
    for _ in range(4):
        stripped = re.sub(
            r"^[\d\s,;.]*?\d{1,2}\.\d{1,2}(?:\.\d{2,4})?\.?\s*[-–—]?\s*",
            "", t)
        if stripped == t:
            break
        t = stripped
    t = re.sub(r"\s*\d{1,2}\.\d{1,2}(?:\.\d{2,4})?\.?\s*[-–—]\s*перенос.*$", "", t)
    t = re.sub(r"^[\s.,;]+", "", t)
    # После удаления «№н. 5-13» от скобки остаётся «(лек» без закрывающей.
    # Дописываем её, иначе название вида занятия обрывается.
    if t.count("(") > t.count(")"):
        t += ")"
    # После удаления пометок мог остаться только мусор из точек и запятых.
    if not re.search(r"[А-Яа-яЁёA-Za-z]", t):
        return ""
    return t


# --- работа с объединёнными ячейками -----------------------------------------

class Sheet:
    """Обёртка над листом xlrd, которая понимает объединённые ячейки."""

    def __init__(self, sheet):
        self.s = sheet
        self._origin: dict[tuple[int, int], tuple[int, int]] = {}
        self._span: dict[tuple[int, int], tuple[int, int]] = {}
        for r1, r2, c1, c2 in sheet.merged_cells:
            for r in range(r1, r2):
                for c in range(c1, c2):
                    self._origin[(r, c)] = (r1, c1)
            self._span[(r1, c1)] = (r2, c2)

    def raw(self, r: int, c: int) -> str:
        """Текст без разворота мержа — для определения шапки."""
        if r >= self.s.nrows or c >= self.s.ncols:
            return ""
        return str(self.s.cell_value(r, c)).strip()

    def text(self, r: int, c: int) -> str:
        """Текст с разворотом мержа: из объединённой ячейки берём верхнюю левую."""
        r0, c0 = self._origin.get((r, c), (r, c))
        return self.raw(r0, c0)

    def span(self, r: int, c: int) -> tuple[int, int]:
        return self._span.get((r, c), (r + 1, c + 1))

    def is_merged_down(self, r: int, c: int) -> bool:
        """Ячейка объединена по вертикали — значит пара идёт обе недели."""
        _, c2 = self.span(r, c)
        r2, _ = self.span(r, c)
        return r2 - r > 1

    @property
    def nrows(self) -> int:
        return self.s.nrows

    @property
    def ncols(self) -> int:
        return self.s.ncols


# --- разбор листа ------------------------------------------------------------

def _faculty(sheet: Sheet) -> tuple[str, str]:
    """Факультет из шапки листа: (код, полное имя).

    В файлах два варианта написания: «ГОРНО-ТЕХНОЛОГИЧЕСКИЯ ФАКУЛЬТЕТА»
    и «ГОРНО-ТЕХНОЛОГИЧЕСКОГО ФАКУЛЬТЕТА» — поэтому ищем по корню.
    """
    for r in range(min(8, sheet.nrows)):
        for c in range(min(3, sheet.ncols)):
            v = sheet.text(r, c).upper()
            if "ГОРНО" in v:
                return "GTF", "Горно-технологический"
            if "ЭЛЕКТРОЭНЕРГЕТИК" in v:
                return "FEU", "Электроэнергетики, экономики и управления"
    return "", ""


def _year(sheet: Sheet) -> int:
    """Учебный год из шапки: «2026-2027» -> 2026.

    Нужен, чтобы разобрать даты без года: «09.11» — это 2026 год.
    """
    for r in range(min(10, sheet.nrows)):
        for c in range(min(4, sheet.ncols)):
            m = re.search(r"(20\d{2})\s*[-–]\s*(20\d{2})", sheet.text(r, c))
            if m:
                return int(m.group(1))
    return datetime.date.today().year


def _course(sheet: Sheet) -> int:
    for r in range(min(8, sheet.nrows)):
        for c in range(min(3, sheet.ncols)):
            m = re.search(r"(\d)\s*КУРС", sheet.text(r, c).upper())
            if m:
                return int(m.group(1))
    return 1


def _header_row(sheet: Sheet) -> int:
    """Строка шапки — та, где есть «День недели» или «Дни»."""
    for r in range(min(12, sheet.nrows)):
        for c in range(min(3, sheet.ncols)):
            v = sheet.text(r, c).lower()
            if "день" in v or v == "дни":
                return r
    raise VuzParseError("Не найдена строка шапки (ожидалась «День недели»)")


def _time_column(sheet: Sheet, header: int, first_group: int) -> int:
    """Колонка с метками времени.

    Обычно одна, но в листе «ФЭЭиУ 1 курс» в колонке 1 лежат реальные
    часы занятий, а сетка — в колонке 2. Поэтому считаем, в какой колонке
    больше всего меток, похожих на сетку.
    """
    best, best_count = first_group - 1, -1
    for c in range(1, first_group):
        count = sum(1 for r in range(header + 1, sheet.nrows)
                    if TIME_RE.match(sheet.raw(r, c)))
        # При равенстве берём правую колонку: в листе «ФЭЭиУ 1 курс»
        # слева лежат реальные часы (15:00:00 - 16:20:00), а сетка
        # пар — правее, ближе к группам.
        if count >= best_count:
            best, best_count = c, count
    return best


def _groups(
    sheet: Sheet, header: int, time_col: int
) -> list[tuple[int, str, int | None]]:
    """Колонки групп: (индекс колонки, имя, индекс колонки кабинета).

    Кабинет лежит в отдельной колонке сразу после группы («ЭК-26-1»,
    «ауд», «МН-26», «ауд», …). Раньше эти колонки просто отбрасывались,
    и все 717 кабинетов и 43 ссылки на Teams терялись.

    Ищем по позиции, а не по ``c + 1``: «ГП-26» занимает две колонки в
    шапке, и после мержа «ауд» может оказаться не соседней.
    """
    result: list[tuple[int, str, int | None]] = []
    seen: set[str] = set()
    for c in range(time_col + 1, sheet.ncols):
        name = sheet.text(header, c).strip()
        if not name:
            continue
        low = name.lower()
        # Колонка кабинета относится к предыдущей найденной группе.
        if "ауд" in low:
            if result and result[-1][2] is None:
                result[-1] = (result[-1][0], result[-1][1], c)
            continue
        # «ГП-26» занимает две колонки в шапке: вторая — продолжение
        # мержа, а не вторая группа. Оставляем только первую.
        if name in seen:
            continue
        seen.add(name)
        if low in SERVICE:
            continue
        # «ЭЭ-25 (6,9,12,15)» — суффикс в скобках это недели, не часть имени
        clean = re.sub(r"\s*\([\d,\s]+\)\s*$", "", name).strip()
        if clean:
            result.append((c, clean, None))
    return result


def _row_para(sheet: Sheet, r: int, time_col: int) -> int | None:
    """Номер пары, если с этой строки начинается блок.

    Используется ``raw``, а не ``text``: объединённая ячейка времени
    отдаёт своё значение и на второй строке блока, из-за чего та
    выглядела бы началом новой пары.
    """
    t = sheet.raw(r, time_col)
    if not t or not TIME_RE.match(t):
        return None
    return para_from_time(t)


# Что бывает в колонке «ауд» кроме кабинета: «н.»/«ч.» — чётность
# недели, «Айка»/«ЭИОС» — электронная среда, а при горизонтальном мерже
# туда перетекает текст самой пары («Геология (прак.) Иванов И.И.»).
# Всё это кабинетом не является и раньше попадало в поле room.
_ROOM_JUNK = {"н.", "ч.", "н", "ч", "айка", "эиос", "н.э.", "ч.э."}


def _cell_room(sheet: Sheet, row: int, col: int) -> str:
    """Кабинет из колонки «ауд» для этой строки.

    Мерж: одна ячейка кабинета часто накрывает весь блок пары, поэтому
    если в своей строке пусто — поднимаемся к началу мержа.
    """
    text = sheet.text(row, col)
    if not text or not text.strip():
        origin = sheet._origin.get((row, col))
        if origin and origin[0] != row:
            text = sheet.text(origin[0], col)
    text = (text or "").strip()
    if not text:
        return ""
    # Ссылка на онлайн-пару: не обрезаем по 64 символам — иначе она
    # превратится в неработающий огрызок.
    if text.lower().startswith(("http://", "https://")):
        return text
    text = " ".join(text.split())
    low = text.lower().strip(" .")
    if low in _ROOM_JUNK:
        return ""
    # Кабинет короткий и без пробелов: «М-406», «А-101», «307». Всё, что
    # длиннее или содержит больше одного слова, — перетёкший текст пары.
    if len(text) > 20 or len(text.split()) > 1:
        return ""
    return text[:64]


def _cell_lessons(
    sheet: Sheet, r: int, c: int, group: str, weekday: int, para: int,
    upper: bool, covers_both_weeks: bool = False,
    room_col: int | None = None,
) -> list[VuzLesson]:
    """Разобрать одну ячейку пары в уроки.

    ``upper`` — верхняя строка пары (нечётная неделя). Пара занимает две
    строки; ячейка, объединённая через обе половины блока, относится к
    обеим неделям.

    В ячейке может быть: пусто, только пометка чётности (значит на этой
    неделе пары нет), один предмет, два предмета с разными неделями или
    время начала внутри текста («с 18.50 - ...»).
    """
    text = sheet.text(r, c)
    if not text or not text.strip():
        return []

    # Клетка с датой — это перенос или разовая замена, а не постоянная
    # пара. В базовое расписание ей нельзя: она либо задвоит слот, либо
    # повиснет на весь семестр. Замены собирает _cell_changes.
    if is_move(text):
        return []

    result: list[VuzLesson] = []
    carried = ""      # название предмета из первой части ячейки
    for chunk in split_by_weeks(text):
        # Время в начале ячейки задаёт реальный номер пары.
        real_para, chunk = inline_para(chunk)
        parsed = _parse_chunk(
            chunk, group, weekday, real_para or para, upper,
            covers_both_weeks, carry=carried)
        if parsed:
            result.extend(parsed)
            # Запоминаем название для следующей части: она может быть
            # без него («; пр. №н. 18) Иванов И.И.»).
            carried = _base_name(parsed[0].subject) or carried

    # ФИО обычно одно на всю ячейку и стоит в последней части. Разносим
    # его на части без преподавателя, иначе лекция останется безымянной.
    known = {l.teacher for l in result if l.teacher}
    if len(known) == 1:
        only = known.pop()
        for lesson in result:
            if not lesson.teacher:
                lesson.teacher = only

    # Кабинет или ссылка на онлайн-пару: в источнике это отдельная
    # колонка «ауд» рядом с группой. 43 ячейки в файле — ссылки на
    # Teams; без них дистанционную пару невозможно посетить.
    if room_col is not None:
        room = _cell_room(sheet, r, room_col)
        if room:
            for lesson in result:
                lesson.room = room
    return result


# Обрывки вида занятия, которые остаются после деления по «;».
KIND_ONLY = {"лек", "прак", "лаб", "пр", "лек.", "прак.", "лаб.", "пр.",
             "сем", "сем."}


def _base_name(subject: str) -> str:
    """Название предмета без вида занятия: «Страхование (лек.)» -> «Страхование».

    Скобка бывает незакрытой: в ячейке «Электрические машины (лаб.»
    просто обрезан текст. Такой хвост тоже убираем.
    """
    t = re.sub(r"\s*\([^)]*\)\s*$", "", subject).strip()
    t = re.sub(r"\s*\([^)]*$", "", t).strip()
    if t.lower().strip(" .,;()") in KIND_ONLY:
        return ""
    return t


def _parse_chunk(
    chunk: str, group: str, weekday: int, para: int, upper: bool,
    covers_both_weeks: bool, carry: str = "",
) -> list[VuzLesson]:
    body = clean_subject(chunk)
    if not body:
        return []
    # Вторая часть вида «(лек. №н. 8-18) Носкова Е.М.» не содержит
    # названия предмета — оно осталось в первой части.
    if carry and body.lstrip().startswith("("):
        body = f"{carry} {body}"

    # В ячейке текст бывает продублирован (объединённая ячейка с повтором),
    # тогда «№н. 12» встречается дважды. Склеиваем через запятую, чтобы
    # «12 12» не превратилось в непарсимую строку.
    weeks = parse_week_list(
        ",".join(m.group(1) for m in WEEK_LIST_RE.finditer(chunk)))

    if weeks:
        # Список недель задаёт недели точнее любой чётности: в нём бывают
        # смешанные наборы вроде (6,7,8,...). Оставляем ANY, конкретную
        # неделю выбирает materialize() по дате.
        parity = PARITY_ANY
    elif covers_both_weeks:
        parity = PARITY_ANY
    else:
        parity = PARITY_ODD if upper else PARITY_EVEN

    subject, teacher = split_teacher(body)
    # Скобки не срезаем: в них вид занятия — «(прак.)». Иначе остаётся
    # обрубок «прак» и вид занятия теряется.
    subject = subject.strip(" .,;")
    # Часть после «;» бывает без названия предмета: «(лек. №н.6,8; пр. №н. 18)
    # Багомедова У.М.». Тогда название берём из первой части, а вид занятия
    # и преподавателя — из этой.
    if carry and not _base_name(subject):
        kind = _kind(f"({subject})")
        subject = f"{carry} ({kind})" if kind else carry
    if not subject or not _base_name(subject):
        return []
    return [VuzLesson(group, weekday, para, parity, subject, teacher,
                      weeks=weeks)]


def parse_sheet(book, sheet_name: str) -> VuzSheet:
    """Разобрать один лист книги."""
    sheet = Sheet(book.sheet_by_name(sheet_name))
    header = _header_row(sheet)
    faculty, faculty_name = _faculty(sheet)
    course = _course(sheet)

    # Сначала находим колонку времени по всему листу, потом по ней — группы.
    # Обратный порядок зацикливается: группы ищутся правее времени.
    time_col = _time_column(sheet, header, sheet.ncols)
    groups = _groups(sheet, header, time_col)
    year = _year(sheet)
    if not groups:
        raise VuzParseError(f"Лист «{sheet_name}»: не найдено ни одной группы")

    lessons: list[VuzLesson] = []
    changes: list[VuzChange] = []
    meta: list[VuzGroup] = [
        VuzGroup(name=g + VUZ_SUFFIX, faculty=faculty, course=course, form="full")
        for _, g, _room in groups
    ]

    weekday = 0
    for r in range(header + 1, sheet.nrows):
        day_text = sheet.text(r, 0).strip()
        if DAY_RE.match(day_text):
            weekday = _weekday_number(day_text)
        if not weekday:
            continue
        para = _row_para(sheet, r, time_col)
        if para is None:
            continue

        # Блок пары — объединённая ячейка времени. Она бывает на 2 строки
        # (обычный случай) и на 4-5, когда в одну пару стоит несколько
        # предметов. Верхняя половина блока — нечётная неделя, нижняя —
        # чётная. Мерж внутри половины означает «одна пара на эти строки»,
        # а не «обе недели»: обе недели — это когда текст совпал в обеих
        # половинах, и такое схлопывается ниже.
        r2, _ = sheet.span(r, time_col)
        r2 = min(r2, sheet.nrows)
        half = max(1, (r2 - r) // 2)

        for c, g, room_col in groups:
            for offset, row in enumerate(range(r, r2)):
                # Датированные ячейки — это замены, а не постоянное
                # расписание. Забираем их отдельно, чтобы не попали в базу.
                cell = sheet.text(row, c)
                if cell and is_move(cell):
                    changes.extend(_cell_changes(
                        cell, g + VUZ_SUFFIX, para, year))
                upper = offset < half
                # Мерж, накрывающий обе половины блока, — пара каждую
                # неделю. Считаем только вертикальные мержи: горизонтальный
                # мерж (общая лекция на несколько групп) недель не касается.
                span_r2, _ = sheet.span(row, c)
                origin = sheet._origin.get((row, c), (row, c))
                merged_down = span_r2 - origin[0] > 1
                covers = merged_down and span_r2 >= r2
                lessons.extend(_cell_lessons(
                    sheet, row, c, g + VUZ_SUFFIX, weekday, para,
                    upper=upper, covers_both_weeks=covers,
                    room_col=room_col))

    lessons = _merge_slot_clash(_merge_same_subject(_dedupe(lessons)))
    return VuzSheet(lessons=lessons, groups=meta, changes=changes)


def _merge_slot_clash(lessons: list[VuzLesson]) -> list[VuzLesson]:
    """Склеить разные предметы, попавшие в один слот на одни и те же недели.

    Такое встречается, когда в ячейке стоит два предмета через «;» или
    два списка недель. Показать их двумя строками нельзя: у них один
    номер пары. Склеиваем в одну строку через « / ».
    """
    result: list[VuzLesson] = []
    index: dict[tuple, VuzLesson] = {}
    for lesson in lessons:
        key = (lesson.group, lesson.weekday, lesson.para, lesson.parity,
               lesson.weeks)
        found = index.get(key)
        if found is None:
            index[key] = lesson
            result.append(lesson)
            continue
        if lesson.subject not in found.subject:
            found.subject = f"{found.subject} / {lesson.subject}"
        if lesson.teacher and lesson.teacher not in found.teacher:
            found.teacher = (f"{found.teacher}, {lesson.teacher}"
                             if found.teacher else lesson.teacher)
    return result


def _merge_same_subject(lessons: list[VuzLesson]) -> list[VuzLesson]:
    """Склеить лекцию и практику одного предмета в одном слоте.

    В вузе бывает «Страхование (лек.)» и «Страхование (прак.)» в одну
    пару на одни и те же недели. Студенту это одна пара, а не две.
    """
    result: list[VuzLesson] = []
    index: dict[tuple, VuzLesson] = {}
    for lesson in lessons:
        base = _base_name(lesson.subject)
        key = (lesson.group, lesson.weekday, lesson.para, lesson.parity,
               lesson.weeks, base)
        found = index.get(key)
        if found is None:
            index[key] = lesson
            result.append(lesson)
            continue
        # Дополняем вид занятия, если он ещё не упомянут.
        kind = _kind(lesson.subject)
        if kind and kind not in found.subject:
            found.subject = f"{found.subject} + {kind}"
        # Дописываем, а не заполняем пустое: лекцию и практику могут
        # вести разные люди. Раньше второй исчезал, и студент шёл на
        # практику, не зная преподавателя; в его расписании пары тоже
        # не было, потому что она записана на первого.
        if lesson.teacher and lesson.teacher not in found.teacher:
            found.teacher = (f"{found.teacher}, {lesson.teacher}"
                             if found.teacher else lesson.teacher)
    return result


def _kind(subject: str) -> str:
    """Вид занятия из скобок: «лек.», «прак.», «лаб.»."""
    m = re.search(r"\(([^)]*)\)\s*$", subject)
    return m.group(1).strip(" .") if m else ""


def _dedupe(lessons: list[VuzLesson]) -> list[VuzLesson]:
    """Убрать точные дубли.

    Ячейка, объединённая на две строки внутри половины блока, попадает
    в разбор дважды. Схлопывать ODD+EVEN в ANY здесь нельзя: недели
    задаются по-разному, и «одинаковый текст в двух половинах» бывает
    просто двумя разными предметами в одну пару.
    """
    seen: dict[tuple, VuzLesson] = {}
    for lesson in lessons:
        # room в ключе: две пары одного предмета в разных кабинетах —
        # не дубль, а разные занятия (например, подгруппы).
        key = (lesson.group, lesson.weekday, lesson.para, lesson.parity,
               lesson.subject, lesson.teacher, lesson.room, lesson.weeks)
        seen.setdefault(key, lesson)
    return list(seen.values())


def _cell_changes(
    text: str, group: str, para: int, year: int,
) -> list[VuzChange]:
    """Разобрать датированную ячейку в одну или несколько замен."""
    date = parse_date(text, year)
    if date is None:
        return []
    body = clean_subject(text)
    if not body:
        return []
    subject, teacher = split_teacher(body)
    action = SUB_CANCEL if re.search(r"отмен", text, re.I) else SUB_REPLACE
    return [VuzChange(group=group, date=date, para=para, subject=subject,
                      teacher=teacher, action=action)]


def _weekday_number(name: str) -> int:
    order = ["понедельник", "вторник", "среда", "четверг",
             "пятница", "суббота", "воскресенье"]
    return order.index(name.strip().lower()) + 1


# --- точка входа -------------------------------------------------------------

def parse(data: bytes, form: str = "full") -> VuzSheet:
    """Разобрать файл `.xls` целиком.

    ``form`` — форма обучения: full (очная), part (очно-заочная).
    """
    try:
        book = xlrd.open_workbook(file_contents=data, formatting_info=True)
    except Exception as exc:
        raise VuzParseError(f"Не удалось открыть xls: {exc}") from exc

    all_lessons: list[VuzLesson] = []
    all_groups: list[VuzGroup] = []
    all_changes: list[VuzChange] = []
    for name in book.sheet_names():
        try:
            parsed = parse_sheet(book, name)
        except VuzParseError:
            raise
        except Exception as exc:
            raise VuzParseError(f"Лист «{name}» не разобрался: {exc}") from exc
        all_lessons.extend(parsed.lessons)
        all_changes.extend(parsed.changes)
        for g in parsed.groups:
            g.form = form
        all_groups.extend(parsed.groups)

    if not all_lessons:
        raise VuzParseError("В файле не найдено ни одной пары")

    return VuzSheet(lessons=all_lessons, groups=all_groups,
                    changes=all_changes)
