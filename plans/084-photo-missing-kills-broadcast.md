# План 084: пропавшее фото роняет всю рассылку

**Приоритет:** низкий (файлы не пропадают сами), но последствия —
полная остановка рассылки для всех 224 подписчиков.

**Трудоёмкость:** S (одна ветка `except`).

## Проблема

`send_photo` (`broadcaster.py:47`) ловит только ошибки Telegram:

```python
try:
    await bot.send_photo(user_id, FSInputFile(photo), caption=caption)
except exceptions.TelegramBadRequest as e:
    ...
except exceptions.TelegramForbiddenError:
    ...
except exceptions.TelegramRetryAfter as e:
    ...
except exceptions.TelegramAPIError:
    ...
else:
    return True
return False
```

Ошибки файловой системы не ловятся ни одной из этих ветвей.
`FSInputFile` — обёртка над путём, файл читается позже, в
`bot.send_photo`:

```python
async def read(self, bot: "Bot") -> AsyncGenerator[bytes, None]:
    async with aiofiles.open(self.path, "rb") as f:   # <- здесь
        while chunk := await f.read(self.chunk_size):
            yield chunk
```

Если файла нет — `FileNotFoundError` вылетает из `send_photo` наружу.
В `broadcast_schedule` (`broadcaster.py:83`) тоже нет `try`:

```python
for user_id, text, photo in items:
    if photo:
        ok = await send_photo(bot, user_id, photo, text)   # <- вылетит здесь
    ...
```

Значит падает **весь цикл**, а не одна отправка. Подписчики, до которых
очередь не дошла, не получат расписание вообще.

## Проверено на живом боте

```
CONSTRUCTED ok, path = /data/photos/monday/NOSUCHFILE.jpg
READ RAISED: FileNotFoundError [Errno 2] No such file or directory
```

Конструктор проходит (файл не трогает), чтение падает. Поймать это
внутри `send_photo` нечем — проверил исходник `Bot.send_photo`:
`try` в нём **ноль**, `except` **ноль**.

## Как файл может пропасть

Путь берётся в `poller.py:183`, отправка — на строке 200, после цикла
по всем подписчикам. Между ними — секунды. За это время:

- админ чистит `/data/photos` через `/photos` (`admin.py:1065`);
- том перемонтирован или освобождён (сейчас `-v /home/virprom/.../data:/data`);
- файл переименован вручную.

Вероятность мала. Но если случится, симптом будет не «одно фото не
ушло», а «рассылка встала на середине».

## Что сделать

Добавить ветку до `TelegramAPIError` (она ловит только `TelegramAPIError`,
`OSError` мимо неё):

```python
except OSError:
    logging.exception("Target [ID:%s]: фото недоступно: %s", user_id, photo)
```

Или проверять существование до отправки:

```python
if not os.path.exists(photo):
    logging.warning("фото пропало: %s", photo)
    return await send_message(bot, user_id, caption)   # текст без картинки
```

Второй вариант лучше: подписчик получит расписание текстом, а не
ничего.

## Что на проде

```
/data/photos/monday      16 файлов
/data/photos/tuesday     14
/data/photos/wednesday   11
/data/photos/thursday    12
/data/photos/friday      10
/data/photos/saturday     8
/data/photos/sunday      11
итого                    82
```

Все семь папок непусты, `list_photos` отрабатывает. Пропаж сейчас нет —
дефект латентный.

## Проверено и признано корректным

**`send_photo` без `photo` не вызывается.** Проверил `poller.py:183,
196` — оба места оборачивают в `if ... send_image`, а `random_photo`
возвращает `None`, если папка пуста. `broadcast_schedule` тоже
проверяет `if photo:`. Путь `None` в `FSInputFile` не попадёт.

**`rate` в `broadcast_schedule` разумный.** `delay = 1.0 / max(rate,
0.1)`; при `rate=20` — 50 мс между сообщениями. На 224 подписчиках это
11 секунд. Лимит Telegram ~30 msg/s глобально — не превышается.

**Рекурсия при `RetryAfter`** — уже [план 044](044-retry-recursion.md),
включая непойманный `RecursionError`. Дублировать не стал.

## Риски

- **`except OSError` шире, чем нужно.** Поймает и `PermissionError`, и
  `IsADirectoryError`. Для логирования это нормально: любая причина —
  фото не уйдёт, надо отправить текст.
- **Текст без фото — не то, что человек ждал.** Но лучше, чем ничего.
  Если решат иначе, `return False` тоже приемлемо — рассылка
  продолжится, один человек останется без картинки.
