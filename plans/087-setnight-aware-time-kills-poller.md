# План 087: `/setnight` принимает время с часовым поясом — поллер замолкает

**Приоритет:** высокий. Одна опечатка админа останавливает обновление
расписания молча.

**Трудоёмкость:** S (одна строка проверки + 1 тест).

## Проблема

`admin.py:360` — `/setnight` валидирует время так:

```python
try:
    datetime.time.fromisoformat(parts[1])
    datetime.time.fromisoformat(parts[2])
except ValueError:
    await message.answer("Формат времени: HH:MM")
    return
```

`fromisoformat` — **принимает больше, чем «HH:MM»**:

```
'23:00'              -> 23:00:00           ок
'07:00:00'           -> 07:00:00           ок
'23'                 -> 23:00:00           ок
'23:00+03:00'        -> 23:00:00+03:00     <-- AWARE
'23:00:00.123456'    -> 23:00:00.123456    ок
'25:00'              -> ValueError         отбито
'7:00'               -> ValueError         отбито
```

Строка сохраняется в настройки **как есть**:

```python
await repo.settings.set("night_start", parts[1])   # "23:00+03:00"
```

`SettingRepo.set` пишет `value: str` без разбора — пояс остаётся в БД.

## Что произойдёт

`_in_night` (`poller.py:203`) читает обе строки и сравнивает с `now`:

```python
start = datetime.time.fromisoformat(start_str)   # aware: 23:00+03:00
end   = datetime.time.fromisoformat(end_str)     # naive: 07:00
...
t = now.time()                                    # naive
if start < end:                                   # <- TypeError
```

Проверил на живом коде:

```
TypeError: can't compare offset-naive and offset-aware times
```

Дальше `poller_loop` (`poller.py:224`):

```python
while True:
    try:
        settings = await repo.settings.get_all()
        ...
        if not _in_night(now, settings["night_start"], settings["night_end"]):
            if time.monotonic() - last_poll >= interval:
                changes = await poll_once(...)
    except Exception:
        logging.exception("poll failed")
    await asyncio.sleep(10)
```

`TypeError` ловится общим `except Exception`, пишется «poll failed», цикл
живёт — но **`poll_once` не вызывается никогда**. Расписание
перестаёт обновляться, пока админ не вспомнит про `/setnight`.

Архив при этом продолжает писаться: блок `snapshot_past_days` стоит
**выше** `_in_night`, так что `day_snapshot` наполняется, а
`college_lesson` замирает. Расхождение между ними будет расти молча.

## Как админ узнает

Никак. В чат уходит «Ночная пауза: 23:00+03:00–07:00» — выглядит как
успех. В логах `poll failed` каждые 10 секунд, но логи почти не видны
(находка 16), а дежурного у проекта нет.

## Что сделать

Проверять, что время naive и без секунд:

```python
def _parse_hhmm(value: str) -> datetime.time | None:
    try:
        t = datetime.time.fromisoformat(value)
    except ValueError:
        return None
    if t.tzinfo is not None or t.second or t.microsecond:
        return None
    return t
```

Тогда `23:00+03:00`, `07:00:00` и `23` отбиваются с понятным текстом.

**Плюс защита в `_in_night`** — на случай, если кривое значение уже в
БД (оно могло попасть туда раньше):

```python
if start.tzinfo is not None or end.tzinfo is not None:
    return False
```

Это дешевле, чем падение поллера. Но одна эта строка не заменяет
валидацию: `return False` значит «не ночь», то есть ночная пауза тихо
выключится — лучше, чем мёртвый опрос, но всё равно неправда.

## Проверено и признано корректным

**`/setbell` с aware-временем безопасен.** Проверил экспериментально
на in-memory SQLite: `upsert` с `time(9,25,tzinfo=+03:00)` проходит,
а при чтении приходит `09:25:00` с `tzinfo=None` — колонка `Time`
отбрасывает пояс. Так что там дыра есть, но последствий нет.

**Пустое значение не ломает поллер.** `/setnight off` пишет `""` в обе
настройки, `_in_night` на пустой строке делает `return False` до
разбора — проверено.

**`start == end` не роняет.** `23:00 23:00` вернёт `False` (ночь
выключена) — тихо, но не падает. Отдельная мелочь: админ видит
«Ночная пауза: 23:00–23:00» и думает, что она включена. Стоит
отбивать при вводе — та же проверка `start != end`, что уже есть в
`_in_night`.

**`/setpoll` и `/setrate` проверяют границы.** Не ожидал: `/setpoll`
отбивает `sec < 10`, `/setrate` — `not 0 < rate <= 30`. Оба через
`raise ValueError` внутри `try`, что выглядит хитро, но работает.
То есть соседи по файлу строже, чем `/setnight`, — это и подчёркивает
странность: единственная команда, принимающая время, не проверяет
ничего сверх «парсится».

## Риски

- **Правка затрагивает только `/setnight`.** `/setbell` оставляю как
  есть: там пояс безвреден (см. выше), а сигнатуру всё равно менять в
  [плане 045](045-setbell-breaks-grid.md).
- **Кривое значение уже в БД.** Если админ когда-то ввёл пояс, оно там
  до сих пор. Проверил прод: `night_start`/`night_end` в БД
  **отсутствуют**, работают дефолты `23:00`/`07:00`. Так что чинить
  данные не нужно.
