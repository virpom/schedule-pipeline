# План 158: два поля `ParsedLesson` парсятся и выбрасываются

**Приоритет:** низкий. Ничего не ломает, но код обещает данные, которых
потом нет, и это сбивает при чтении.

**Трудоёмкость:** S (~10 минут).

## Что нашёл

`parsers/eios.py:80-91` — dataclass результата разбора «Очной формы»:

```python
@dataclass(slots=True)
class BaseLesson:
    """Пара из базового расписания."""

    group: str
    course: int | None
    day: int          # 1..6
    para: int         # 1..6
    subject: str
    teacher: str
    parity: str = PARITY_BOTH
    time_note: str | None = None
```

Восемь полей. `replace_base_lessons` (`sync_eios.py:92-103`) переносит
в БД **шесть**:

```python
BaseLesson(
    group=lesson.group,
    week_parity=db_parity(lesson.parity),
    weekday=lesson.day,
    para=lesson.para,
    subject=(lesson.subject or "")[:128],
    teacher=(lesson.teacher or "")[:128],
    room="",
    source=SOURCE_SITE,
    updated_at=now,
)
```

### Поле `course` — 0 использований

Парсится из имени листа (`parse_ochoe:257-258`):

```python
course_match = re.search(r"\d", sheet.title)
course = int(course_match.group()) if course_match else None
```

и кладётся в каждую `BaseLesson(course=course, ...)`.

**Но в модели `BaseLesson` (`infrastructure/database/models/base_lesson.py`)
нет колонки `course`.** Проверил grep'ом по `tgbot/`, `parsers/`,
`infrastructure/`: `lesson.course` встречается **0 раз**.

То есть значение считается для каждого листа и каждой пары — и никуда
не идёт.

### Поле `time_note` — тоже 0 использований

Извлекается из префикса предмета (`parse_ochoe:359`):

```python
lesson.subject, lesson.time_note = _strip_time_note(lesson.subject)
```

`_strip_time_note:230-244` — нетривиальная функция: регулярка, чистка
«до .19:30», схлопывание пробелов. Работает, возвращает осмысленную
строку вида «с 18.00 до 21.00».

**Читается она нигде.** Проверил: `time_note` в `tgbot/`,
`infrastructure/`, `common/` — **0 совпадений**.

## Почему это стоит убрать

**`course` выглядит как данные, которых нет.** Читая
`BaseLesson(course=course)`, легко решить, что курс где-то хранится и
его можно использовать для фильтра. В модели его нет — и запрос
`select(BaseLesson.course)` упадёт.

**`time_note` — 15 строк кода впустую.** Регулярка `_TIME_HEAD_RE`,
два `re.sub`, `re.search`. Всё это выполняется на каждой паре при
каждом разборе (а разбор идёт при каждом изменении файла) и
выбрасывается.

**Вводит в заблуждение при правках.** Если кто-то захочет показать
«с 18.00 до 21.00» в расписании, он найдёт `time_note`, решит, что
осталось только передать его в БД, — и потратит время на выяснение,
что данные уже выкинуты на предыдущем шаге.

## Что сделать

**Вариант А — удалить оба поля (минимальный):**

```python
@dataclass(slots=True)
class BaseLesson:
    group: str
    day: int
    para: int
    subject: str
    teacher: str
    parity: str = PARITY_BOTH
```

Плюс убрать `course_match` из `parse_ochoe` и вызов
`_strip_time_note` (оставив чистку префикса времени, если она нужна
для `subject` — а она нужна: «5-я пара - Физика» должно стать
«Физика»).

**Вариант Б — сохранить `time_note`, если он полезен.** Тогда:
добавить колонку в модель, миграцию, передачу в `BaseLesson(...)` и
показ в `format_day`. Это уже не S, а M, и требует решения продукта.

**`course` удалять смело** — он не нужен ни одному экрану: курс
студента бота берётся из `user.course` (`user.py:528`), а для вуза —
из `vuz_group.course`.

## Проверено и признал корректным

**`room=""` — не потеря.** Проверил живой файл «Очная форма.xlsx»:
в ячейках **0 упоминаний кабинетов**. Искал `каб`, `ауд`, «123 каб».
Источник их просто не содержит. `sync_eios.py:100` пишет пустую строку
потому, что писать нечего.

**`parity` работает.** `db_parity:44-53` отображает `BOTH → ANY`,
`EVEN → EVEN`, `ODD → ODD`, неизвестное → `ANY`. Все три ветки
используются.

**`_strip_time_note` делает полезную работу для `subject`.** Даже если
`time_note` выбросить, сама чистка нужна: без неё в предмет попадёт
«5-я пара - ». Удалять надо только возврат второго значения.

**`_faculty` / `_course` / `_year` в `parsers/vuz.py`** — другой парсер,
там `course` идёт в `VuzGroup` и используется (план 157).

## Риски

- **Удаление поля из dataclass** сломает тесты, если они его читают.
  Проверил `tests/test_eios_parser.py`: `BaseLesson` там не
  инстанцируется напрямую, проверяется через `parse_ochoe`.
- **`_strip_time_note` возвращает кортеж** — при удалении второго
  значения надо поправить и сигнатуру, и вызов на `:359`, иначе
  распаковка `lesson.subject, lesson.time_note = ...` сломается.
