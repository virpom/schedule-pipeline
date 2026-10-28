# План 115: ретрай при флуд-лимите Telegram — неограниченная рекурсия

> **УСТАРЕЛ 27.10.2026.** Рекурсии больше нет: `send_message` и
> `send_photo` не зовут себя, а пишут `e.retry_after` в переданный
> список `retry_after` и возвращают `False`. Сон вынесен наружу — в
> `broadcast_schedule` один сон на всю пачку. `RecursionError`
> недостижим.

**Приоритет:** низкий. За всё время работы 429 не приходил ни разу.
Дефект реальный, но требует отказа Telegram, чтобы проявиться.

**Трудоёмкость:** S (~6 строк).

## Проблема

`send_message` (`broadcaster.py:10`) при `TelegramRetryAfter` **вызывает
сам себя**:

```python
except exceptions.TelegramRetryAfter as e:
    logging.error(
        f"Target [ID:{user_id}]: Flood limit is exceeded. Sleep {e.retry_after} seconds."
    )
    await asyncio.sleep(e.retry_after)
    return await send_message(
        bot, user_id, text, disable_notification, reply_markup
    )  # Recursive call
```

То же самое в `send_photo` (`:59`). Счётчика попыток нет.

## Что произойдёт при отказе

Python по умолчанию допускает 1000 фреймов. Один вызов `send_message`
занимает примерно три (функция, `try`, `except`-ветка). Значит
**примерно 300 последовательных 429** — и `RecursionError`.

Дальше важное: **`RecursionError` не поймается**.

```python
except exceptions.TelegramRetryAfter as e:   # ловит только 429
except exceptions.TelegramAPIError:          # ловит ошибки API
```

`RecursionError` наследуется от `RuntimeError`, а не от
`TelegramAPIError`. Он вылетит из `send_message`, потом из
`broadcast_many`, и попадёт в общий перехват `poller_loop`:

```python
except Exception:
    logging.exception("poll failed")
await asyncio.sleep(10)
```

То есть **вся рассылка оборвётся на середине**, а через 10 секунд
поллер начнёт новый проход. Если Telegram продолжает отказывать —
цикл повторится.

## Насколько это вероятно

Проверил логи прода за всё время:

```
grep -c 'Flood limit'  ->  0
```

**Ни одного 429.** Настройка `notify_rate` = 20 сообщений в секунду при
лимите Telegram около 30 — запас есть.

Значит это не «горит», а «лежит мина». Но мина настоящая: при массовой
рассылке (233 подписчика) и одновременной активности бота запас в 10
сообщений в секунду невелик.

## Что сделать

Заменить рекурсию на цикл с пределом:

```python
async def send_message(
        bot: Bot,
        user_id: Union[int, str],
        text: str,
        disable_notification: bool = False,
        reply_markup: InlineKeyboardMarkup = None,
        _attempts: int = 3,
) -> bool:
    for attempt in range(_attempts):
        try:
            await bot.send_message(user_id, text,
                                   disable_notification=disable_notification,
                                   reply_markup=reply_markup)
        except exceptions.TelegramRetryAfter as e:
            if attempt == _attempts - 1:
                logging.error("Target [ID:%s]: flood limit, сдаюсь", user_id)
                return False
            await asyncio.sleep(e.retry_after)
            continue
        except exceptions.TelegramBadRequest as e:
            logging.error("Target [ID:%s] BadRequest: %s", user_id, e.message)
            return False
        except exceptions.TelegramForbiddenError:
            logging.error("Target [ID:%s]: got TelegramForbiddenError", user_id)
            return False
        except exceptions.TelegramAPIError:
            logging.exception("Target [ID:%s]: failed", user_id)
            return False
        else:
            logging.info("Target [ID:%s]: success", user_id)
            return True
    return False
```

То же для `send_photo`.

## Проверено и признано корректным

**`broadcast_many` и `broadcast_schedule` сами по себе безопасны.**
Цикл `for` с `await asyncio.sleep(delay)` между сообщениями, ошибка
одного получателя не останавливает очередь (`send_message` возвращает
`False`, счётчик `sent` не растёт). Комментарий в коде это и объясняет.

**`delay = 1.0 / max(rate, 0.1)`** — защита от деления на ноль, если
`notify_rate` выставят в 0.

**`recursion` в `broadcast_many` нет** — только в двух листовых
функциях.

## Риски

- **Предел в 3 попытки может отбросить сообщение**, которое дошло бы с
  пятой. Для расписания это приемлемо: следующий проход поллера
  отправит заново, если данные ещё меняются. Но для ручной админской
  рассылки (`/broadcast`) сообщение потеряется молча — счётчик `sent`
  покажет меньше, чем было получателей, и админ это увидит в
  «Готово: отправлено N/M».
- **`retry_after` может быть большим** (до 30 секунд). Три попытки с
  паузой 30 с — это 90 секунд на одного получателя. При 233 адресатах
  рассылка растянется. Стоит ограничить суммарное ожидание, но это уже
  не про рекурсию.
