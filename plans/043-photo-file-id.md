# План 043: фото перезагружается в Telegram на каждую отправку

**Приоритет:** низкий. Работает, но делает лишнюю работу — и это видно
по задержке рассылки.

**Трудоёмкость:** S (~10 строк).

## Проблема

`broadcaster.py:51`:

```python
await bot.send_photo(user_id, FSInputFile(photo), caption=caption)
```

`FSInputFile` читает файл с диска **при каждой отправке**. `file_id`,
который Telegram возвращает в ответе, нигде не сохраняется.

В `notify_new_schedule` фото выбирается внутри двойного цикла:

```python
for date, is_new in sorted(changes, key=lambda x: x[0]):
    weekday = photos.weekday_folder(date)
    for user in subscribers:
        ...
        photo = photos.random_photo(photos_path, weekday) if (user.send_image and not is_teacher) else None
```

То есть `random_photo` вызывается **на каждого пользователя** и делает
`os.listdir` каждый раз.

## Масштаб на проде

Проверил базу:

```
подписаны (subscribed=1): 220 из 227
send_image=1:             15 человек
не teacher:               14
```

То есть фото уходит 14 человекам, текст — 220.

| Сценарий | Фото | Чтение с диска |
|---|---|---|
| 1 дата | 14 | ~5.5 МБ |
| 14 дат (полная материализация) | 196 | ~76 МБ |

Средний размер фото: 31.9 МБ / 82 файла ≈ **390 КБ**. Всего 82 фото в
семи папках (`monday`…`sunday`), 31.9 МБ.

Не катастрофа, но каждая отправка — повторная загрузка того же файла в
Telegram. При 14 датах это 196 загрузок по 390 КБ вместо одной.

**Плюс `os.listdir`** вызывается `220 × дат` раз: при 14 датах — 3080
вызовов. Замерил локально: 3178 вызовов на 16 файлов — 65 мс. Тоже
не катастрофа, но работа впустую.

## Что сделать

Кэшировать `file_id` после первой отправки. Telegram отдаёт его в
`message.photo[-1].file_id`, и повторная отправка по `file_id` не
требует загрузки файла:

```python
async def send_photo(bot, user_id, photo, caption=""):
    try:
        if isinstance(photo, str) and photo.startswith("FILEID:"):
            await bot.send_photo(user_id, photo[7:], caption=caption)
        else:
            msg = await bot.send_photo(user_id, FSInputFile(photo), caption=caption)
            _remember_file_id(photo, msg.photo[-1].file_id)
    ...
```

Хранилище — простой словарь на процесс:

```python
_file_ids: dict[str, str] = {}
```

Переживать рестарт не обязан: при первом запуске после деплоя каждый
файл загрузится один раз, дальше — по `file_id`.

**Заодно — выбрать фото один раз на дату, а не на пользователя.**
Сейчас каждый из 14 получает своё случайное фото; если задумано «одно
фото на день для всех», достаточно поднять `random_photo` на уровень
выше цикла по пользователям:

```python
for date, is_new in sorted(changes, key=lambda x: x[0]):
    weekday = photos.weekday_folder(date)
    day_photo = photos.random_photo(photos_path, weekday)   # один раз
    for user in subscribers:
        photo = day_photo if (user.send_image and not is_teacher) else None
```

Это убирает 3080 `listdir` и делает рассылку однородной. Если же
разные фото — часть задумки, правку не делать.

## Проверено и признано корректным

**`random_photo` безопасен при пустой папке** — возвращает `None`, и
`broadcast_schedule` в этом случае идёт через `send_message`. Проверил:
на проде все семь папок непустые (8–16 файлов).

**`_EXT` фильтр правильный** — `.jpg/.jpeg/.png`, регистр не важен
(`f.lower().endswith`).

**`weekday_folder` не падает на любую дату** — `WEEKDAYS` покрывает
все семь дней, `date.weekday()` даёт 0–6.

**Проблема с `send_image` у преподавателей решена** — в цикле стоит
`and not is_teacher`, иначе преподаватель получал бы картинку с чужой
группой.

## Риски

- **`file_id` привязан к боту.** Если токен сменят, все сохранённые
  `file_id` станут недействительны. Кэш в памяти — не проблема
  (перезапуск его сбросит), но если когда-нибудь положат в БД — надо
  чистить при смене токена.
- **`file_id` может протухнуть** (Telegram чистит старые файлы). Нужен
  fallback: при `TelegramBadRequest` про `file_id` повторить с
  `FSInputFile`. Иначе один битый `file_id` сломает отправку навсегда.
- **Словарь растёт неограниченно** — 82 записи, не проблема.
- **Одно фото на день vs разные** — это продуктовое решение, не
  техническое. Спросить владельца бота, прежде чем менять.
