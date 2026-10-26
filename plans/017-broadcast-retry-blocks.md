# План 017: `retry_after` не должен блокировать всю рассылку

**Приоритет:** низкий. Рассылки пока не отправляются, но код готов.

**Трудоёмкость:** S (~10 строк).

## Проблема

`tgbot/services/broadcaster.py:38`:

```python
except exceptions.TelegramRetryAfter as e:
    logging.error(f"Target [ID:{user_id}]: Flood limit is exceeded. Sleep {e.retry_after} seconds.")
    await asyncio.sleep(e.retry_after)
    return await send_message(bot, user_id, text, disable_notification, reply_markup)
```

`send_message` вызывается из `broadcast_many` в **последовательном
цикле**:

```python
for user_id, text in items:
    if await send_message(bot, user_id, text):
        sent += 1
    await asyncio.sleep(delay)
```

Если один получатель дал `429 retry_after=30`, `asyncio.sleep(30)`
внутри `send_message` **останавливает весь цикл**. Остальные 222
получателя ждут.

**Расчёт:** 227 получателей при `rate=20 msg/s` — это ~11 секунд.
Один `retry_after=30` растягивает до ~41+ секунд. Несколько подряд —
до минут.

## Что смягчает

- `docs/TROUBLESHOOTING.md` упоминает, что `rate` настраивается через
  `setting.notify_rate` (сейчас `20`). При 20 msg/s лимит Telegram
  (~30 msg/s) не достигается, так что 429 должен быть редким.
- Рекурсивный повтор корректен: после сна сообщение всё-таки уйдёт.

## Что сделать

### 1. Не спать внутри `send_message`

Разделить «отправить» и «обработать 429»:

```python
async def send_message(bot, user_id, text, disable_notification=False,
                       reply_markup=None, retry_after=None) -> bool:
    try:
        await bot.send_message(...)
    except exceptions.TelegramRetryAfter as e:
        if retry_after is not None:
            retry_after[0] = max(retry_after[0], e.retry_after)
        return False          # пусть решает вызывающий
    ...
    return True
```

### 2. Спать один раз за весь цикл

```python
async def broadcast_many(bot, items, rate=5.0):
    delay = 1.0 / max(rate, 0.1)
    sent, failed = 0, []
    for user_id, text in items:
        if await send_message(bot, user_id, text):
            sent += 1
        else:
            failed.append((user_id, text))
        await asyncio.sleep(delay)

    # один сон на всю пачку, а не на каждого
    if failed:
        wait = 30
        await asyncio.sleep(wait)
        for user_id, text in failed:
            if await send_message(bot, user_id, text):
                sent += 1
    return sent
```

Это уже лучше, но всё равно приблизительно. Точнее — собрать
`retry_after` из всех неудач и подождать максимум один раз.

### 3. Не терять сообщения

Сейчас `broadcast_many` возвращает `sent` — число успешных. Провалы
не логируются построчно. Добавить:

```python
if failed:
    logging.warning("broadcast_many: %d не доставлено (429/ошибки)", len(failed))
```

## Как проверить

Тест с поддельным ботом, который бросает `TelegramRetryAfter` на первом
вызове:

```python
def test_broadcast_does_not_block_on_retry_after():
    """Один 429 не должен останавливать рассылку остальным."""
    # бот, который на user_id=1 бросает retry_after=30,
    # а на остальных отвечает успешно
    # проверить: отправлено всем, суммарная задержка < 30 с
```

## Риски

- **Не превысить лимит Telegram.** Если убрать сон, повтор может снова
  получить 429. Решение — один сон на пачку с максимальным
  `retry_after`, а не мгновенный повтор.
- **`broadcast_schedule`** (для фото) имеет ту же проблему — править
  вместе.
- **Сейчас не горит:** рассылки не отправляются (пользователь просил
  не запускать). Это задел на будущее, не срочно.
