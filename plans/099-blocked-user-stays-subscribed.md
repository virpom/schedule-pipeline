# План 099: заблокировавший бота остаётся подписчиком навсегда

**Приоритет:** средний. 11 человек из 228 (4.8%) блокируют отправку —
каждый цикл рассылки бот тратит на них 11 запросов и пишет 11 ошибок в
лог, вытесняя полезные записи.

**Трудоёмкость:** S (~5 строк).

## Проблема

`send_message` (`broadcaster.py:16`) ловит `TelegramForbiddenError` и
только логирует:

```python
except exceptions.TelegramForbiddenError:
    logging.error(f"Target [ID:{user_id}]: got TelegramForbiddenError")
```

Возвращает `False`, но **никто не смотрит на результат**.

`broadcast_schedule` (`broadcaster.py:67`) считает только успешные:

```python
for user_id, text, photo in items:
    ok = await send_message(bot, user_id, text)
    if ok:
        sent += 1
    await asyncio.sleep(delay)
```

`False` просто не попадает в счётчик. Состояние `users.subscribed` не
меняется.

## Что это даёт на проде

Логи контейнера забиты повторами. Проверил `docker logs` — одни и те же
11 ID, блоками по 11, без конца:

```
ERROR [root] Target [ID:1026493333]: got TelegramForbiddenError
ERROR [root] Target [ID:6290176575]: got TelegramForbiddenError
... ещё 9 ...
ERROR [root] Target [ID:1026493333]: got TelegramForbiddenError   <- снова
```

Все 15 — **реальные студенты с группами**, не мусор. Проверено на
проде 26.10.2026 19:48, у всех `subscribed=1`:

```
ID           bell_mode   группа
7817486935   start_end   ПРф-25    <- ещё и звонки
1006777316   start_end   СМк-25    <- ещё и звонки
1026493333   off         ЭОф-24
6290176575   off         ТЭк-26
8045525928   off         ЭОк-26
1154994105   off         ЭОк-26
6110035037   off         ЮР-26Б
5049755813   off         ДОУ-24
5350559258   off         ЭКк-26
5517722107   off         СМк-25
1435973306   off         ТЭф-24
1614743583   off         ЮР-24Б
6236704873   off         ТЭк-26
5014894674   off         ТЭк-26
8786019347   off         ЭОк-26
```

Двое с `start_end` получают звонки — примерно 10 событий в день каждый,
то есть ~20 провальных запросов ежедневно только на звонках.

## Почему это дороже, чем «11 лишних запросов»

**Логи перестали быть полезными.** Проверил: `docker logs | grep
'обновлен\|материализ'` даёт **пусто** — записи о синхронизации
вытеснены ошибками. Когда случился инцидент 26.10 в 10:40 (рассылка на
15 дат), в логах не осталось ни одной строки о том, что именно
обновилось. Пришлось восстанавливать картину по `setting.last_sync_ok`
и размерам таблиц.

**Лимит Telegram.** На 228 подписчиков лимит ~30 сообщений в секунду;
`notify_rate=20` по умолчанию. 11 гарантированно провальных запросов
съедают ~5% бюджета каждый цикл — не критично, но бессмысленно.

## Что сделать

Отписывать при `TelegramForbiddenError`:

```python
async def send_message(bot, user_id, text, ...):
    try:
        await bot.send_message(...)
    except exceptions.TelegramForbiddenError:
        logging.warning("Target [ID:%s]: заблокировал бота, отписываю", user_id)
        await mark_unsubscribed(user_id)      # <- новое
        return False
```

**Где взять `mark_unsubscribed`.** `broadcaster.py` не знает про БД —
он получает только `bot`. Проще вернуть особый признак и решать в
`notify_new_schedule`:

```python
# broadcaster.py
class Blocked(Exception):
    pass
...
except exceptions.TelegramForbiddenError:
    raise Blocked(user_id)

# poller.py, notify_new_schedule
for user_id, text, photo in items:
    try:
        await send_message(bot, user_id, text)
    except Blocked as b:
        await repo.users.set_subscribed(b.user_id, False)
```

Либо добавить `session_pool` в `broadcast_schedule` — но это тянет
БД-зависимость в модуль отправки, что хуже.

**Не отписывать на `TelegramBadRequest`.** Он бывает за «message is too
long» или «chat not found» — первое лечится обрезкой, второе значимо,
но не всегда означает блокировку. Только `ForbiddenError` — это
однозначное «пользователь заблокировал бота».

## Проверено и признано корректным

**Рассылка не падает на ошибке.** `send_message` возвращает `False`,
`broadcast_schedule` считает `sent` и продолжает — проверил, цикл не
прерывается. Так что это не сбой доставки, а утечка состояния.

**Чаты — отдельный случай, покрыт планом 085.** [План 085](085-chat-cannot-be-unlinked.md)
разбирает `Forbidden` для **чатов** (бот выгнан из группы) и предлагает
`ChatRepo.remove` + обработчик `my_chat_member`. Здесь речь о
**пользователях**: у них есть `subscribed`, который можно просто
снять — удалять запись не нужно, человек вернётся, разблокировав.

**`send_photo` тоже ловит `Forbidden`.** `broadcaster.py:56` — та же
проблема, но фото уходит только `send_image=True` (15 человек), и
заблокированные среди них могут не быть. Чинить вместе.

## Риски

- **Ложная отписка.** `ForbiddenError` приходит и когда пользователь
  удалил аккаунт — тогда отписка правильна. Но если бот временно
  ограничен (редкий случай), человек потеряет подписку и не узнает.
  Компромисс: отписывать после **двух** подряд `Forbidden`, для чего
  нужен счётчик. Минимальная правка — сразу.
- **Обратная связь.** Разблокировав бота, человек не подпишется
  автоматически. Стоит в `/start` проверять `subscribed` и предлагать
  включить — сейчас `subscribed` при создании `0`, так что новичок и
  так должен нажать «Подписка».
