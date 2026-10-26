# План 109: звонок помечается отправленным до отправки — при сбое теряется навсегда

**Приоритет:** средний. Задевает 16 человек, которые включили звонки.
Сбой редкий, но последствие необратимое.

**Трудоёмкость:** S (~6 строк).

## Проблема

`bell.py:89-97`:

```python
for t, key, text in events:
    if t != now_min:
        continue
    async with session_pool() as db:
        repo = RequestsRepo(db)
        if await repo.reminders.is_sent(user.id, today, key):
            continue
        await repo.reminders.mark_sent(user.id, today, key)   # <- :96 коммит
    await send_message(bot, user.id, text)                     # <- :97 отправка
```

**Порядок неверный.** Сначала в базу пишется «отправлено», потом
делается попытка отправить. `mark_sent`
(`bell_reminder.py:21`) коммитит транзакцию сразу:

```python
await self.session.execute(
    insert(BellReminder).values(...).on_conflict_do_nothing(...))
await self.session.commit()
```

`send_message` (`broadcaster.py:10`) при `TelegramForbiddenError`
возвращает `False` — но возвращаемое значение **никто не смотрит**.

## Что происходит при сбое

1. `mark_sent` пишет строку, коммитит.
2. `send_message` получает `TelegramForbiddenError` (человек заблокировал
   бота), логирует и возвращает `False`.
3. Цикл идёт дальше, `False` отброшен.

Человек не получил звонок. Повтора не будет: `is_sent` на следующем
тике вернёт `True`. **Напоминание потеряно навсегда.**

То же при `TelegramBadRequest` (битый текст, слишком длинное сообщение)
и при `TelegramAPIError` (сеть, 500 от Telegram).

## Масштаб

`bell_mode != 'off'` — **16 человек** из 238. Из них двое
(`7817486935` ПРф-25, `1006777316` СМк-25) **уже заблокировали бота** —
это те, кто даёт по 8 `Forbidden` за 8 часов. Для них каждый звонок
помечается отправленным и теряется.

## Что сделать

Проверять результат и откатывать отметку при неудаче:

```python
for t, key, text in events:
    if t != now_min:
        continue
    async with session_pool() as db:
        repo = RequestsRepo(db)
        if await repo.reminders.is_sent(user.id, today, key):
            continue
    sent = await send_message(bot, user.id, text)
    if sent:
        async with session_pool() as db:
            repo = RequestsRepo(db)
            await repo.reminders.mark_sent(user.id, today, key)
```

Шесть строк перестановки. Отметка ставится **после** успешной отправки.

**Но остаётся гонка:** между `is_sent` и `mark_sent` тик может
случиться дважды (цикл раз в 30 секунд, окно маленькое). Защита уже
есть — `on_conflict_do_nothing` на уникальном индексе. Дубль не
создастся, но и сообщение может уйти дважды. Вероятность мала:
`_tick` вызывается последовательно, а не параллельно.

## Проверено и признано корректным

**`on_conflict_do_nothing` защищает от дублей.** Индекс
`(user_id, date, event_key)` уникален — проверил в модели. Повторная
вставка не падает.

**`is_sent` перед `mark_sent` внутри одной сессии — корректно.** Обе
операции идут в одном `async with session_pool()`, транзакция общая.

**Заблокированные не ломают цикл.** `send_message` ловит
`TelegramForbiddenError` и возвращает `False` — исключение не
вылетает, остальные пользователи обрабатываются.

**`snapshot_past_days` работает, дефекта нет.** Проверил на проде:
0.29 с на проход, снимки за 23.10 и 24.10 полные (0 групп с парами
без снимка). Пробел 20.10 — исторический: снимки созданы 23.10 в
21:26, а расписание вуза впервые появилось в `college_lesson` только
24.10. Код не виноват.

**`get_groups()` трижды за проход — не проблема.** Замер: весь проход
0.29 с, из них 387 запросов `exists()` — 0.12 с. Вынос `get_groups()`
из цикла сэкономит два запроса из четырёхсот. Не стоит правки.

## Риски

- **Повторная отправка при падении между `send_message` и `mark_sent`.**
  Если процесс умрёт ровно в этом окне, человек получит звонок дважды.
  Это лучше, чем не получить вовсе — но окно есть.
- **`send_message` возвращает `True` и при частичном успехе?** Нет:
  `return True` стоит только в `else` после успешного `await`. Проверил.
- **Тест.** Стоит добавить: замокать `send_message` на `False` и
  проверить, что `is_sent` остался `False`.
