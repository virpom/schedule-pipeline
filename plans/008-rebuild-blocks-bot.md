# План 008: правка старосты не должна блокировать бота на 3.6 с

**Приоритет:** восьмой. Регрессия, внесённая 25.10. Один староста на
пару секунд блокирует всех.

**Трудоёмкость:** M (правка в `editor.py` + `materialize_day`).

## Проблема

`tgbot/handlers/editor.py:881` `_rebuild`:

```python
async def _rebuild(repo, date=None):
    from tgbot.services import sync_eios
    try:
        if date is None:
            await sync_eios.materialize(repo)        # ВСЕ 14 дней
        else:
            await sync_eios.materialize_day(repo, date)
    except Exception:
        logging.exception("не удалось пересобрать college_lesson")
```

Правка **базы** повторяется каждую неделю, поэтому пересобираются все
14 дней. Замерено на копии боевой БД:

| Операция | Время |
|---|---|
| `materialize` (14 дней, 129 групп) | **3.58 с** |
| `materialize_day` (1 день) | **0.19 с** |

Разница в 19 раз. При 129 группах полная пересборка делает
~1806 вызовов `get_day_slots`.

## Почему это проблема, а не «просто медленно»

1. **Староста ждёт.** Нажал «Сохранить» → 3.6 с тишины → ответ.
   Telegram ждёт ответа callback до ~15 с, запас есть, но UX плохой.

2. **SQLite блокирует БД.** WAL не включён (см. план 010),
   `journal_mode=delete`, `busy_timeout=5000`. Пока идёт пересборка,
   любая запись из другого обработчика ждёт. `DatabaseMiddleware`
   пишет `users` **на каждое событие** (UPSERT + commit). При двух
   старостах одновременно второй получит
   `sqlite3.OperationalError: database is locked`.

3. **42 коммита.** `materialize` вызывает `replace_date` на каждый день
   (2 коммита: delete + insert) плюс `set_hash`. Итого до 42 fsync
   за проход.

## Что сделать

### 1. Пересобирать только затронутые дни недели

Правка базы действует на конкретный `weekday` + `parity`. Значит нужно
пересобрать только те дни в 14-дневном окне, которые попадают на этот
`weekday` и эту чётность — это **2 дня**, а не 14.

Сигнатура `_rebuild` расширяется:

```python
async def _rebuild(repo, date=None, weekday=None, parity=None):
    """Пересобрать college_lesson после правки.

    Правка базы повторяется каждую неделю, но только в свой день
    недели и свою чётность — поэтому пересобираем два дня из
    четырнадцати, а не все.
    """
    from tgbot.services import sync_eios
    try:
        if date is not None:
            await sync_eios.materialize_day(repo, date)
        elif weekday is not None:
            await sync_eios.materialize_weekday(repo, weekday, parity)
        else:
            await sync_eios.materialize(repo)
    except Exception:
        logging.exception("не удалось пересобрать college_lesson")
```

Новая функция `materialize_weekday` в `sync_eios.py`:

```python
async def materialize_weekday(repo, weekday: int, parity: str | None = None) -> int:
    """Пересобрать дни окна, попадающие на weekday (и чётность)."""
    from tgbot.services.schedule_layer import PARITY_OFFSET, week_parity
    today = datetime.date.today()
    written = 0
    for offset in range(MATERIALIZE_DAYS):
        date = today + datetime.timedelta(days=offset)
        if date.isoweekday() != weekday:
            continue
        # PARITY_OFFSET обязателен: колледж считает чётность не по ISO.
        if parity and parity != "ANY" and week_parity(date, PARITY_OFFSET) != parity:
            continue
        await materialize_day(repo, date)
        written += 1
    return written
```

Вызывать из `cb_edit_base` и `cb_del_base`:

```python
await _rebuild(repo, weekday=weekday, parity=parity)
```

### 2. Не дублировать код пересборки дня

`materialize_day` (добавлен 25.10) повторяет ~45 строк `materialize`.
Перед расширением — вынести общий сборщик строк:

```python
async def _day_rows(repo, date) -> list[dict]:
    """Строки college_lesson на дату: ручные + сгенерированные."""
    ...

async def materialize_day(repo, date):
    await repo.college_lessons.replace_date(date, await _day_rows(repo, date))

async def materialize(repo, days=MATERIALIZE_DAYS):
    for offset in range(days):
        await materialize_day(repo, today + timedelta(days=offset))
```

Это уменьшит файл и снимет риск, что две копии разъедутся.

### 3. Замер после правки

```bash
# на копии БД
.venv/bin/python -c "замер materialize_weekday"
```

Ожидаемо: ~0.4 с вместо 3.58 с (2 дня × 0.19).

## Как проверить

```bash
.venv/bin/python -m pytest tests/test_sync_eios.py tests/test_schedule_layers.py -q
```

Вживую: староста правит пару → ответ должен прийти за <1 с, а студент
той же группы — увидеть правку сразу.

## Риски

- **Пропустить день.** Если `weekday`/`parity` переданы неверно, часть
  дней не пересоберётся, и студент увидит старое до следующего поллера
  (5 минут). Это мягкая деградация, не потеря данных.
- **`parity="ANY"`** — правка действует каждую неделю, значит нужно
  пересобрать все дни с этим `weekday` (обычно 2 из 14). Проверить
  ветку.
- **Замены (`date is not None`)** — уже работают через
  `materialize_day`, не трогать.
