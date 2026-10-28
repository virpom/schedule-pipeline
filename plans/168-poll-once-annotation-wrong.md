# План 168: `poll_once` возвращает три значения, а обещает два

> **УСТАРЕЛ 28.10.2026.** Устарел: оба `return` в poll_once отдают `changes`, аннотация и докстринг совпадают с кодом. Тройки значений нет ни в одном месте.

**Приоритет:** низкий. Сейчас код работает — распаковка в
`notify_new_schedule` ждёт три и получает три. Врёт только аннотация и
докстринг, то есть документация для следующего читателя.

**Трудоёмкость:** S (две строки).

## Что происходит

`poller.py:53` — сигнатура:

```python
async def poll_once(bot, session_pool, config: Config) -> list[tuple[datetime.date, bool]]:
```

`poller.py:55-61` — докстринг:

```
Возвращает список изменившихся дней (для рассылки): ``(дата, новое_ли)``.
```

`poller.py:62` — переменная:

```python
changes: list[tuple[datetime.date, bool]] = []
```

А `poller.py:168` кладёт **три** элемента:

```python
changes.append((date, had_lessons == 0 and date == today, changed[date]))
```

И `poller.py:164` — получатель — ждёт три:

```python
async def notify_new_schedule(bot, session_pool, changes: list[tuple[datetime.date, bool, set[str]]], rate: float, photos_path: str) -> None:
```

Распаковка (`:175`):

```python
for date, is_new, groups in sorted(changes, key=lambda x: x[0]):
```

## Почему это важно

Код **функционально верен** — три значения кладутся, три и
распаковываются. Дефект в другом: аннотация и докстринг описывают
другую функцию. Читатель, поверивший им, напишет
`for date, is_new in poll_once(...)` — и получит `ValueError: too many
values to unpack` в рантайме, уже на проде.

Третий элемент — `set[str]` с группами, чьи пары изменились. Он
появился позже (рассылка перестала будить всех подряд), а сигнатуру и
докстринг тогда не поправили.

## Почему это не ловится

**`mypy` не установлен** и не настроен — ни в `requirements-dev.txt`,
ни в конфиге:

```
$ .venv/bin/python -m mypy --version
No module named mypy
```

**`pyflakes` не ловит** несоответствия типов — он ищет неиспользуемые
имена и неопределённые переменные. На `poller.py` даёт **0**
замечаний.

**CI нет** — [план 013](013-ci-and-linting.md) предлагает завести, но
в списке инструментов там `pyflakes`, а не `mypy`.

Проверил на изолированной установке: `mypy` ловит ровно это.

```
$ mypy t.py
t.py:6: error: Argument 1 to "append" of "list" has incompatible type
"tuple[date, bool, set[str]]"; expected "tuple[date, bool]"  [arg-type]
Found 1 error in 1 file (checked 1 source file)
```

## Что сделать

```python
async def poll_once(
        bot, session_pool, config: Config,
) -> list[tuple[datetime.date, bool, set[str]]]:
```

```python
    changes: list[tuple[datetime.date, bool, set[str]]] = []
```

Докстринг:

```
Возвращает список изменившихся дней (для рассылки):
``(дата, первый_ли_запуск, изменившиеся_группы)``. Пустой набор групп
означает «что именно поменялось — неизвестно», тогда будим всех.
```

## Что ещё стоит завести

Аннотация — симптом. Корень в том, что **типы никто не проверяет**.
Стоит добавить в `requirements-dev.txt`:

```
mypy~=1.13
```

и прогнать `mypy --ignore-missing-imports tgbot/ common/ infrastructure/`.
Первый прогон даст много замечаний (код писался без типизации), но
даже `--follow-imports=skip` на одних сервисах поймал бы этот случай.
Это расширение [плана 013](013-ci-and-linting.md), не отдельная работа.

## Проверено и признал корректным

**Функционально всё верно.** `changes.append(...)` кладёт три,
`for date, is_new, groups in ...` распаковывает три. Ошибки в рантайме
нет.

**`notify_new_schedule` аннотирован правильно** — `:164` уже с тремя
элементами. Ошибка только на стороне `poll_once`.

**Других таких расхождений в проекте нет.** Проверил все
`list[tuple[...]]`:

| Место | Элементов | Кладёт/читает |
|---|---|---|
| `parsers/vuz.py:460` | 2 | 2 |
| `parsers/eios.py:383` | 4 | 4 |
| `parsers/eios.py:497` | 2 | 2 |
| `parsers/eios.py:594` | 2 | 2 |
| `bell.py:48` | 3 | 3 |
| `broadcaster.py:69` | 3 | 3 |
| `broadcaster.py:91` | 2 | 2 |
| `poller.py:172` | 3 | 3 |
| **`poller.py:53,62`** | **2** | **3** |

## Риски

- **Правка чисто декларативная** — поведение не меняется. Проверить
  можно только `mypy`, а его нет. Без него правка держится на глазах
  ревьюера.
- **Заведение `mypy` может выдать сотни замечаний** на существующем
  коде. Начинать стоит с `--follow-imports=skip` и постепенно, иначе
  первый прогон похоронит идею.
