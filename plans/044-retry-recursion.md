# План 044: бесконечная рекурсия при `TelegramRetryAfter`

> **СДЕЛАНО 27.10.2026** (коммит `692aa75`). Отметка стояла в
> `plans/README.md`, но не в файле плана.

**Приоритет:** низкий по вероятности, высокий по последствиям: одна
застрявшая отправка может уронить всю рассылку и задачу поллера.

**Трудоёмкость:** S (~8 строк).

## Проблема

`broadcaster.py:31` и `:56` — обе функции повторяют себя рекурсивно:

```python
except exceptions.TelegramRetryAfter as e:
    logging.error(f"Target [ID:{user_id}]: Flood limit. Sleep {e.retry_after}s")
    await asyncio.sleep(e.retry_after)
    return await send_message(bot, user_id, text, disable_notification, reply_markup)
    #      ^^^ рекурсивный вызов
```

Предела глубины нет. Если Telegram снова ответит `RetryAfter`, вызов
уйдёт на следующий уровень, и так до `RecursionError`.

## Когда это срабатывает

**Сценарий 1 — `retry_after == 0`.** Telegram в редких случаях отдаёт
ноль. Тогда `asyncio.sleep(0)` не ждёт, вызов повторяется немедленно,
снова получает `RetryAfter 0`, и стек растёт до тысячи за доли секунды.
Дальше — `RecursionError`, который **не перехвачен** (кроме
`TelegramAPIError`), то есть вылетает наружу.

**Сценарий 2 — устойчивое превышение лимита. Проверил — закрыт.**
`/setrate` (`admin.py:350`) валидирует верхнюю границу:

```python
if not 0 < rate <= 30:
    raise ValueError
```

То есть поставить 60 нельзя, а 30 — предел личных чатов Telegram.
Этот путь в рекурсию не ведёт.

Проверил прод: `notify_rate` в таблице `setting` **отсутствует**,
берётся из `DEFAULTS` = 20. Запас есть.

## Последствия

`broadcast_schedule` вызывается из `notify_new_schedule`, а тот — из
`poller_loop`:

```python
changes = await poll_once(bot, session_pool, config)
if changes:
    await notify_new_schedule(bot, session_pool, changes, rate, config.photos_path)
last_poll = time.monotonic()
```

`RecursionError` не пойман внутри `notify_new_schedule` — он
поднимется в `poller_loop`, где есть `except Exception`, и запишется в
лог. То есть **поллер не умрёт**, но:

1. Рассылка оборвётся на середине — часть людей получит уведомление,
   часть нет, и повторной попытки не будет.
2. `last_poll` **не обновится** (исключение до него), поэтому
   следующий тик снова вызовет `poll_once`. Это скорее хорошо:
   пропущенное догонится.
3. Если `RetryAfter` приходит на каждого получателя, каждый вызов
   будет рекурсировать — и рассылка будет падать снова и снова.

## Что сделать

Заменить рекурсию на цикл с ограничением:

```python
async def send_message(bot, user_id, text, disable_notification=False,
                       reply_markup=None, _retries: int = 2) -> bool:
    for attempt in range(_retries + 1):
        try:
            await bot.send_message(...)
            return True
        except exceptions.TelegramRetryAfter as e:
            if attempt == _retries:
                logging.error("Target [ID:%s]: Flood limit, сдаюсь", user_id)
                return False
            wait = max(float(e.retry_after or 0), 1.0)
            logging.warning("Target [ID:%s]: Flood limit, жду %.0fs", user_id, wait)
            await asyncio.sleep(wait)
        except exceptions.TelegramForbiddenError:
            logging.error("Target [ID:%s]: заблокировал бота", user_id)
            return False
        except exceptions.TelegramAPIError:
            logging.exception("Target [ID:%s]: failed", user_id)
            return False
    return False
```

Ключевое — `max(float(e.retry_after or 0), 1.0)`: ноль превращается в
секунду, и цикл гарантированно завершается.

То же для `send_photo`.

**`notify_rate` уже ограничен — правка не нужна.** Проверил
`/setrate`: `if not 0 < rate <= 30`. Верхняя граница есть.

**А вот `/setpoll` верхней границы не имеет** (`admin.py:328`):

```python
sec = int(parts[1])
if sec < 10:
    raise ValueError
```

`/setpoll 999999` пройдёт — и поллер будет опрашивать сайт раз в
11 дней. Это отдельная мелочь, не про рекурсию.

## Проверено и признано корректным

**`TelegramForbiddenError` обрабатывается верно** — не ретраится,
потому что человек заблокировал бота, и повтор бессмысленен.

**`TelegramBadRequest` тоже не ретраится** — правильно: это ошибка
данных (слишком длинный текст, битый `file_id`), повтор не поможет.

**`asyncio.sleep(e.retry_after)` — не блокирует другие задачи.**
`poller_loop` и `bell_loop` живут в одном событийном цикле, и сон
одной корутины не мешает другой. То есть `bell_loop` продолжит
отправлять звонки, пока рассылка ждёт.

**Порядок `except` правильный** — `TelegramBadRequest` и
`TelegramForbiddenError` стоят **до** `TelegramAPIError`, иначе
поймались бы общим обработчиком.

## Риски

- **Ограничение повторов `_retries=2` может потерять сообщение**, если
  Telegram просит подождать дольше. Но потеря одного уведомления лучше
  падения всей рассылки. При `retry_after=30` и двух повторах
  отправка займёт до минуты — приемлемо.
- **`max(retry_after, 1.0)` занижает ожидание**, если Telegram просит
  60 с. Это осознанно: лучше сдаться и записать в лог, чем держать
  задачу минутой на каждого получателя.
- **`/setpoll` без верхней границы** — админ может случайно поставить
  999999 и остановить синхронизацию. Чинится там же, отдельной строкой.
