# План 001: не стирать расписание при пустом разборе

> **СДЕЛАНО** (`068e576`). `parse_ochoe` поднимает `EiosParseError`
> на пустом разборе; тесты `test_parse_ochoe_raises_on_empty_sheet` и
> `test_parse_ochoe_raises_when_groups_found_but_no_lessons` на месте.
>
> Проверено 27.10.2026 вызовом на пустом листе: исключение поднимается.

**Приоритет:** первый. Единственная находка, где тихо уничтожается
расписание всех 222 студентов колледжа, и в логе не будет ошибки.

**Трудоёмкость:** S (~20 строк + 2 теста).

## Проблема

`parsers/eios.py:248` `parse_ochoe()` при неудачном разборе возвращает
`[]` — без исключения. Шапка групп читается из **фиксированной строки 3**:

```python
for col in range(3, sheet.max_column + 1):
    value = sheet.cell(3, col).value
```

Если на сайте добавят строку сверху (или сдвинут таблицу), `groups`
останется пустым, цикл по строкам не выполнится, и функция вернёт `[]`.

Дальше `tgbot/services/sync_eios.py:288` `_sync_ochoe()`:

```python
lessons = await asyncio.to_thread(eios.parse_ochoe, data)
count = await replace_base_lessons(repo, lessons)   # удалит все site-пары
```

`replace_base_lessons` удаляет все строки `source='site'` и вставляет
ноль. В лог уходит `log.info("базовое расписание обновлено: 0 пар")` —
выглядит как обычная работа.

**Проверено на копии боевой БД:** `replace_base_lessons(repo, [])`
вернул 1954 и стёр все 704 колледжеские пары (вузовские уцелели, они
`source='manual'`). Затем `materialize` собирает `college_lesson` без
них, и 222 студента видят «Занятий нет 🙌» на все 14 дней.

## Почему это дыра

Остальные три источника уже защищены, а этот — нет:

| Источник | Защита |
|---|---|
| `parse_substitutions` | `raise EiosParseError` если нет заголовков с датой |
| `vuz.parse` | `raise VuzParseError("В файле не найдено ни одной пары")` |
| звонки `_sync_bells` | `if slots:` перед записью |
| **`parse_ochoe`** | **нет** |

## Что сделать

### 1. Поднять исключение в парсере

В `parsers/eios.py`, в конце `parse_ochoe` перед `return lessons`:

```python
if not lessons:
    raise EiosParseError(
        "В файле очного расписания не найдено ни одной пары — "
        "вероятно, изменилась структура листа"
    )
```

Это ровно тот приём, что уже применён в `vuz.parse` (строка 797) и
`parse_substitutions` (строка 404). Не изобретать новый механизм.

### 2. Добавить тест

В `tests/test_eios_parser.py`, рядом с остальными тестами `parse_ochoe`:

```python
def test_parse_ochoe_raises_on_empty_sheet():
    """Пустой лист — ошибка, а не «ноль пар».

    Раньше возвращался пустой список, и sync заменял расписание на пустое:
    студенты видели «Занятий нет» вместо старого расписания.
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "1 курс"
    buf = BytesIO()
    wb.save(buf)
    with pytest.raises(EiosParseError):
        parse_ochoe(buf.getvalue())
```

Проверить, что имя исключения и импорт уже есть в файле тестов
(`EiosParseError` импортируется — свериться с шапкой).

### 3. Проверить, что `_step` не съест исключение молча

`sync_eios.py:245` `_step` ловит `Exception` и пишет в `failed`. После
правки парсера путь будет:

1. `parse_ochoe` бросает `EiosParseError`.
2. `_step` ловит, добавляет `"очное расписание"` в `failed`.
3. `sync_once` возвращает `{"ochoe": False, "failed": ["очное расписание"]}`.
4. `poll_once` пишет `logging.warning("частичный сбой синхронизации")`.
5. **Данные в `base_lesson` целы** — это главное.

Пункт 4 всё ещё слабый (см. план 004 про тревоги), но потеря данных
устранена.

## Как проверить

```bash
cd /Users/virprom/schedule-pipeline
.venv/bin/python -m pytest tests/test_eios_parser.py -q
```

Затем вручную, на копии БД — что стирания не происходит:

```python
# после правки: parse бросает, до replace_base_lessons дело не доходит
from parsers import eios
try:
    eios.parse_ochoe(пустой_xlsx)
except eios.EiosParseError:
    print("ок: исключение, данные не тронуты")
```

## Риски

- **Ложное срабатывание.** Если сайт отдаст легально пустое расписание
  (каникулы), бот будет тревожить админа. Проверить: на проде в файле
  всегда есть пары (2658 базовых строк). Если такой случай появится,
  ослабить до `if not lessons and len(sheet_titles) > 0`.
- **Не трогать** `parse_bells` — там уже есть `if slots:` в вызывающем
  коде, дублировать защиту не нужно.
