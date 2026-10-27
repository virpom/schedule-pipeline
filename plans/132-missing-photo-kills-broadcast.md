# План 132: отсутствующий файл фото убивает всю рассылку

> **СДЕЛАНО 27.10.2026** (коммит `89ba01b`).
>
> `except OSError` в `send_photo` — одного хватает на FileNotFoundError
> и PermissionError. Плюс try вокруг каждого получателя в
> `broadcast_schedule` и `broadcast_many`: второй уровень на случай
> неожиданного исключения.

**Приоритет:** средний. Один пропавший файл — и оставшиеся пользователи
не получают расписание вообще.

**Трудоёмкость:** S (~6 строк).

## Проблема

`send_photo` (`broadcaster.py:44`) ловит только исключения Telegram:

```python
async def send_photo(bot, user_id, photo, caption="") -> bool:
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

Файл при этом открывается **лениво**, внутри `await bot.send_photo`:

```python
# aiogram/input_file.py
async def read(self, bot) -> AsyncGenerator[bytes, None]:
    async with aiofiles.open(self.path, "rb") as f:   # <- здесь
        while chunk := await f.read(self.chunk_size):
            yield chunk
```

Проверил на проде: конструктор `FSInputFile('/data/photos/nonexistent.jpg')`
проходит **без ошибки** — путь просто запоминается. Ошибка возникает
позже, при чтении:

```
FileNotFoundError: [Errno 2] No such file or directory:
  '/data/photos/nonexistent_xyz.jpg'
```

## Почему это не ловится

`FileNotFoundError` — не подкласс `TelegramAPIError`. Проверил:

```
FileNotFoundError: подкласс TelegramAPIError = False
PermissionError:   подкласс TelegramAPIError = False
OSError:           подкласс TelegramAPIError = False
```

Ни один из четырёх `except` его не перехватит. Исключение вылетает
из `send_photo` наружу, в `broadcast_schedule`:

```python
for user_id, text, photo in items:
    if photo:
        ok = await send_photo(bot, user_id, photo, text)   # <- падает здесь
    else:
        ok = await send_message(bot, user_id, text)
    if ok:
        sent += 1
    await asyncio.sleep(delay)
```

Цикл **не обёрнут в try** — падение прерывает рассылку целиком.
Оставшиеся пользователи не получают ничего.

## Окно уязвимости

`random_photo` (`photos.py:25`) возвращает путь из `list_photos`, то есть
файл **существовал в момент листинга**. Но между листингом и отправкой
его могут удалить.

Прикинул окно:

```
broadcast_schedule идёт последовательно, delay = 1/rate = 50 мс
18 пользователей с send_image=1  ->  ~0.9 с на паузы
+ сеть на каждый send_photo ~200-500 мс  ->  ~6.3 с всего
```

**~6 секунд**, в течение которых удаление файла ломает рассылку.

## Как файл может пропасть

**Удаления фото в боте нет.** Проверил `grep` по `admin.py`:
`ph_del`, `os.remove`, `unlink` — **0 совпадений**. Загрузка есть
(`upload_photo`), удаления нет.

Значит файл исчезает только снаружи:

- **Bind-mount на хостовую папку** — проверил:
  `bind /home/virprom/schedule-pipeline/data -> /data`. Файлы переживают
  пересоздание контейнера, но любой с доступом к серверу может их
  тронуть.
- **Опечатка в пути** — если `photos_path` в конфиге указывает не туда,
  `list_photos` вернёт `[]` и `random_photo` вернёт `None`. Безопасно.
- **Файл не картинка** — `list_photos` фильтрует по расширению, но не
  проверяет содержимое. Битый `.jpg` даст ошибку от Telegram, а её
  `TelegramBadRequest` **поймает**. Безопасно.

То есть основной риск — ручное вмешательство или гонка при
переименовании. Редко, но последствие — не «одно фото не ушло», а
«половина подписчиков не получила расписание».

## Что сделать

Обернуть чтение файла в ту же защиту:

```python
async def send_photo(bot, user_id, photo, caption="") -> bool:
    try:
        await bot.send_photo(user_id, FSInputFile(photo), caption=caption)
    except exceptions.TelegramBadRequest as e:
        ...
    except OSError:                      # FileNotFoundError, PermissionError
        logging.error("Target [ID:%s]: файл фото недоступен: %s", user_id, photo)
        return False
    ...
```

`OSError` — базовый класс для `FileNotFoundError` и `PermissionError`,
одного `except` хватит.

**Дополнительно:** обернуть тело цикла в `broadcast_schedule` и
`broadcast_many`, чтобы любое неожиданное исключение на одном
получателе не роняло всю очередь:

```python
for user_id, text, photo in items:
    try:
        ok = await send_photo(...) if photo else await send_message(...)
    except Exception:
        logging.exception("broadcast: сбой на %s, продолжаем", user_id)
        ok = False
```

## Что проверил и признал корректным

**`send_message` защищён лучше.** У него нет файловой операции, а все
реальные ошибки — подклассы `TelegramAPIError`. Правки не требует.

**`random_photo` возвращает `None`, если папки нет.** `list_photos`
(`photos.py:14`) проверяет `os.path.isdir` и возвращает `[]`. Значит
отсутствующая папка безопасна — `photo=None`, уйдёт текст.

**Файлы на месте.** Проверил `/data/photos`:

```
monday 16, tuesday 14, wednesday 11, thursday 12,
friday 10, saturday 8, sunday 11  (82 файла)
```

**18 пользователей с `send_image=1`** — они и есть группа риска.

**Нулевое покрытие тестами.** Проверил: `broadcaster.py` не упоминается
ни в одном тестовом файле (`0 тестовых файлов`). То же у `notify_edits.py`
и `photos.py`. Значит регрессию поймать нечем — тест стоит добавить
вместе с правкой.

## Риски

- **`except OSError` может скрыть реальную проблему с диском.** Если
  диск переполнен или смонтирован только для чтения, все фото будут
  молча не отправляться. Логирование обязательно.
- **`except Exception` в цикле** может замаскировать ошибку
  программирования (например, `AttributeError` при смене схемы данных).
  Компромисс: ловить, но с `logging.exception`, чтобы след остался.
