# План 150: alembic глушит все INFO-логи приложения

> **СДЕЛАНО 27.10.2026** (коммит `0101056`). Закрыт вместе с планом 015.
>
> В `migrations/env.py` `fileConfig` вызывается только если у root ещё
> нет хендлеров — ровно как предлагалось. Ручные вызовы `alembic` из
> консоли работают как раньше: там логирование не настроено.
>
> Проверено на проде: формат в логах снова `poller.py:284 #INFO
> [2026-10-27 01:34:22,730] - root - poller started`, а не
> `INFO  [alembic...]`. Все 10 `logging.info` из списка в плане теперь
> доходят.

**Приоритет:** высокий. Логи — единственный способ узнать, что бот
делает. Сейчас 10 INFO-точек пишут в пустоту, включая старт поллера,
старт звонков и итоги рассылок.

**Трудоёмкость:** S (одна строка).

## Проблема

`main.py:22` настраивает логирование:

```python
def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(filename)s:%(lineno)d #%(levelname)-8s [%(asctime)s] - %(name)s - %(message)s",
    )
```

А `main.py:44` сразу после этого применяет миграции:

```python
await run_migrations(engine, config)
```

`migrations_runner.py` вызывает `command.upgrade(cfg, "head")`, alembic
читает `migrations/env.py:17`:

```python
if config.config_file_name is not None:
    fileConfig(config.config_file_name)
```

**`fileConfig` перетирает конфигурацию целиком** — уровень, формат,
хендлеры. А в `alembic.ini:129`:

```ini
[logger_root]
level = WARNING
```

## Проверил на живом контейнере

```
=== после setup_logging() ===
  root.level = 20 (INFO)
  handlers   = [<StreamHandler <stderr> (NOTSET)>]

=== после fileConfig(alembic.ini) — как делает env.py:18 ===
  root.level = 30 (WARNING)
  handlers   = ['StreamHandler']
  format     = ['%(levelname)-5.5s [%(name)s] %(message)s']

WARNI [root] а это WARNING — виден всегда
```

INFO-сообщение, отправленное между этими шагами, **не появилось**.

## Что это значит на практике

Смотрю логи контейнера — 94 строки за 11 часов работы:

```
INFO  [alembic.runtime.migration] Context impl SQLiteImpl.
INFO  [alembic.runtime.migration] Will assume non-transactional DDL.
ERROR [root] Target [ID:7817486935]: got TelegramForbiddenError
ERROR [root] Target [ID:1006777316]: got TelegramForbiddenError
WARNI [root] ЭИОС недоступен: 504 ...
WARNI [root] частичный сбой синхронизации: ['замены']
```

Формат — `INFO  [alembic...]`, а не `main.py:22 #INFO ...`. Это
подтверждает, что `fileConfig` сработал последним.

**`poller started` отсутствует**, хотя `poller.py:244` его пишет первым
делом. Поллер работает — замены и уведомления идут, — но факт запуска
не залогирован.

## Что потеряно

Все 10 `logging.info` в проекте:

```
bell.py:100            "bell loop started"
notify_edits.py:50     "notify_group_about_edit: %s на %s → %d/%d"
notify_edits.py:84     "snapshot_past_days: сохранено %d дней"
broadcaster.py:40      "Target [ID:%s]: success"
broadcaster.py:88      "broadcast_schedule: %d/%d sent at %.1f msg/s"
broadcaster.py:108     "broadcast_many: %d/%d sent at %.1f msg/s"
poller.py:244          "poller started"
migrations_runner.py:71 "alembic: существующая БД — помечаю как %s"
migrations_runner.py:73 "alembic: пустая БД — применяю все миграции"
migrations_runner.py:78 "alembic: миграции применены"
```

Три из них — **итоги рассылки**. Именно их не хватало, когда
разбирались, сколько людей получили уведомления.

## Почему это особенно мешает

`WARNING` и `ERROR` проходят, поэтому в логах видно только плохое:
`TelegramForbiddenError`, `частичный сбой синхронизации`, `504`. Успехи
не видны вовсе.

Картина получается искажённой: кажется, что бот только и делает, что
падает. На самом деле 94 строки — это всё, что прошло фильтр, а
остальное молча потеряно.

## Что сделать

В `migrations/env.py` не вызывать `fileConfig`, либо вызывать с
`disable_existing_loggers=False` и не трогать root. Минимально —
проверить, что логирование уже настроено, и не перетирать:

```python
if config.config_file_name is not None and not logging.getLogger().handlers:
    fileConfig(config.config_file_name)
```

Либо просто убрать строку: приложение настраивает логирование само, а
`alembic.ini` нужен только для ручных вызовов `alembic` из консоли.

## Что проверил и признал корректным

**`setup_logging` сам по себе работает.** Проверил: после него
`root.level = INFO`, один `StreamHandler` на stderr с нужным форматом.

**Миграции применяются.** `alembic_version = 0006_action`, база
поднялась до head. Проблема только в логировании.

**`snapshot_past_days` работает.** Проверил `day_snapshot`:
20.10 — 34 группы, 21.10 — 95, 22.10 — 107, 23.10 — 95, 24.10 — 72.
Числа верные: в субботу 24.10 из 129 групп пары есть у 72, остальные
57 (41 из них `@vuz`) в субботу не учатся. Проверил перебором всех
129 групп через `get_day_slots`.

**`get_groups()` в цикле `snapshot_past_days:74`** вызывается трижды
вместо одного раза, но стоит 3.7 мс на три вызова — не дефект.

**Логи 19.10 и раньше отсутствуют законно.** Контейнер стартовал
26.10 в 11:51, `snapshot_past_days` смотрит `range(1, 4)` — то есть
23, 24, 25 октября. Двадцать пятое — воскресенье, пропускается.
Снапшоты 20-24.10 остались от прошлого запуска.

## Риски

- **Убрать `fileConfig` целиком** — при ручном запуске `alembic upgrade`
  из консоли логи alembic пойдут в дефолтном формате. Некритично.
- **`logging.info` в `broadcaster.py:40`** пишется на **каждого**
  получателя. При рассылке на 234 человека это 234 строки. После
  починки лог вырастет — стоит понизить до `debug` в том же плане.
