# План 074: откат отвечает на callback дважды — Telegram отвечает ошибкой

**Приоритет:** низкий. Пользователь ничего не замечает, но каждый откат
пишет тревогу в лог, а лог и так почти не виден (находка 16).

**Трудоёмкость:** S (две строки).

## Проблема

`cb_undo` (`editor.py:830`) в конце вызывает `cb_log`, чтобы перерисовать
журнал:

```python
await repo.edit_log.delete(last.id)
await cb.answer(msg, show_alert=True)     # <- ответ №1
await cb_log(cb, repo)
```

А `cb_log` (`editor.py:799`) — это полноценный обработчик кнопки, он
завершается своим `cb.answer()`:

```python
async def cb_log(cb: CallbackQuery, repo: RequestsRepo):
    ...
    await cb.message.edit_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(...),
    )
    await cb.answer()                      # <- ответ №2
```

На один и тот же `callback_query_id` уходит два `answerCallbackQuery`.

## Почему это ошибка

Telegram Bot API отвечает на callback **один раз**. Второй вызов
возвращает:

```
400 Bad Request: query is too old and response timeout expired or query ID is invalid
```

Проверил в установленном aiogram 3.13.1 — защиты нет:

```python
>>> import inspect, aiogram
>>> aiogram.__version__
'3.13.1'
>>> src = inspect.getsource(CallbackQuery.answer)
>>> '_answered' in src
False
```

`answer()` просто собирает `AnswerCallbackQuery(callback_query_id=self.id)`
и отправляет. Флага «уже ответили» в объекте нет.

## Что видит каждая сторона

**Староста:**

```
┌──────────────────────────────────┐
│ ↩️ Добавленная пара убрана       │  <- show_alert, показался
└──────────────────────────────────┘
📜 Последние правки
[↩️ Откатить последнюю]
[⬅️ Назад]
```

Всё выглядит правильно. Второй `answer` уходит в пустоту.

**Лог:**

```
aiogram.event: ERROR - Update id=... is not handled.
  Cause: TelegramBadRequest: Bad Request: query is too old ...
```

То есть каждый откат добавляет строку в лог — при том что сама операция
успешна. А логи и без того почти не видны (находка 16), так что в
редких случаях, когда их читают, там будет этот шум.

## Что сделать

Вариант первый — не отвечать второй раз. Вынести тело `cb_log` в
функцию, которая только рисует:

```python
async def _render_log(cb: CallbackQuery, repo: RequestsRepo) -> None:
    """Перерисовать журнал. Не отвечает на callback."""
    ...
    await cb.message.edit_text(...)


@editor_router.callback_query(F.data == "ed:log")
async def cb_log(cb: CallbackQuery, repo: RequestsRepo):
    if not await editor_group(repo, cb.from_user.id):
        await cb.answer("Нет прав", show_alert=True)
        return
    await _render_log(cb, repo)
    await cb.answer()
```

И в `cb_undo`:

```python
await cb.answer(msg, show_alert=True)
await _render_log(cb, repo)      # без второго ответа
```

Вариант второй, минимальный — убрать `cb.answer()` из `cb_log` и
отвечать в вызывающем:

```python
@editor_router.callback_query(F.data == "ed:log")
async def cb_log(cb: CallbackQuery, repo: RequestsRepo):
    ...
    await cb.message.edit_text(...)
    # ответ здесь больше не нужен: cb_undo уже ответил,
    # а для прямого нажатия достаточно edit_text
```

Но тогда при прямом нажатии на «📜 Журнал правок» кнопка останется
«крутиться», пока Telegram не сбросит её сам (~30 с). Первый вариант
чище.

## Проверено и признано корректным

**`cb.answer()` до `edit_text` в остальных обработчиках.** Проверил
`grep -c "cb.answer()" tgbot/handlers/editor.py` — 19 вызовов, и в
каждом обработчике ровно один. Двойной только в цепочке
`cb_undo → cb_log`.

**`cb_log` вызывается из одного места.** `grep -n "cb_log"` даёт две
строки: определение на 799 и вызов на 872. Других путей нет — значит
правка не заденет другие сценарии.

**`cb.answer(msg, show_alert=True)` в `cb_undo` — правильный порядок.**
Сначала ответ, потом перерисовка. Если перевернуть, ошибка второго
`answer` всплывёт раньше, чем пользователь увидит сообщение.

**Тесты этого не ловят** и не должны: `cb.answer` в тестах замокан,
сетевого вызова нет. Это баг интеграции с Telegram, а не логики.

## Риски

- **`edit_text` не упадёт на «message is not modified».** Проверил
  `schedule_edit.py`: `get_last` берёт `order_by(id.desc()).limit(1)`,
  `get_recent` — `order_by(id.desc()).limit(10)`. Последняя запись
  всегда входит в десятку, поэтому после `edit_log.delete(last.id)`
  вывод гарантированно меняется (либо пропадает строка, либо весь
  список становится «Правок ещё не было»).
- **`show_alert=True` блокирует.** Пользователь обязан нажать «OK»,
  прежде чем увидит журнал. Это осознанно: сообщение об откате важнее.
