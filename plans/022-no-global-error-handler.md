# План 022: нет глобального обработчика ошибок — сбой выглядит как «зависло»

**Приоритет:** высокий для UX. Любое необработанное исключение оставляет
пользователя с вечным спиннером и без ответа.

**Трудоёмкость:** S (~20 строк).

## Проблема

В `main.py` нет ни `@dp.errors`, ни `errors=` в `Dispatcher(...)`.
Проверено: `grep -rn "errors\|error_handler" main.py tgbot/` → ничего.

При исключении в обработчике aiogram:

1. ловит исключение и пишет traceback в лог,
2. **`cb.answer()` не вызывается**,
3. Telegram держит спиннер на кнопке до таймаута (~15 с),
4. пользователь видит «ничего не произошло» и жмёт снова.

Для `Message`-обработчика ещё хуже: сообщение просто остаётся без ответа,
и человек не знает, дошло ли оно.

## Достижимые пути

### 1. Подделанный `callback_data`

15 мест парсят данные из callback без проверки:

| Файл | Строки |
|---|---|
| `admin.py` | 286, 373, 374, 723, 724, 923, 924, 1118, 1229 |
| `editor.py` | 315, 340, 351, 362, 385 |
| `user.py` | `cb_hist`, `cb_hist_page` |

`callback_data` приходит **от клиента**, его можно подделать (Telegram
не подписывает содержимое кнопки). Примеры:

```python
# user.py:818 — "hist:not-a-date"
date = datetime.date.fromisoformat(cb.data.split(":", 1)[1])   # ValueError

# editor.py:315 — "ed:bday:99"
weekday = int(cb.data.split(":")[2])            # 99
WEEKDAY_FULL[weekday - 1]                        # IndexError

# editor.py:315 — "ed:bday:0"
WEEKDAY_FULL[-1]                                 # молча «Воскресенье»

# admin.py:1118 — "adm:user:abc"
user_id = int(cb.data.split(":")[2])            # ValueError
```

Заметить: `ed:bday:0` **не падает**, а молча показывает воскресенье —
это хуже, чем падение.

### 2. Гонки в БД

`database is locked` при `busy_timeout` (план 010) — обработчик падает
без ответа.

### 3. Внешние данные

`repo` вернул `None` там, где код ждёт объект.

## Что сделать

### 1. Глобальный обработчик

```python
# tgbot/middlewares/errors.py  (или прямо в main.py)
async def on_error(event: ErrorEvent) -> None:
    logging.exception("необработанная ошибка", exc_info=event.exception)

    # Ответить пользователю, чтобы он не ждал.
    if isinstance(event.update.event, CallbackQuery):
        try:
            await event.update.event.answer(
                "⚠️ Что-то пошло не так. Попробуй ещё раз или вернись в меню.",
                show_alert=True)
        except Exception:
            pass
    elif isinstance(event.update.event, Message):
        try:
            await event.update.event.answer(
                "⚠️ Не получилось обработать. Попробуй ещё раз.")
        except Exception:
            pass

    # Админу — с контекстом, но без секретов.
    ...
```

Регистрация в `main.py`:

```python
dp = Dispatcher(storage=MemoryStorage())
dp.errors.register(on_error)
```

### 2. Уведомить админа

Чтобы поломка не жила в тишине:

```python
for admin_id in config.tg_bot.admin_ids:
    try:
        await bot.send_message(admin_id, f"⚠️ Ошибка в боте: {type(exc).__name__}")
    except Exception:
        pass
```

Важно: **не слать полный traceback в Telegram** — там бывают токены
и данные пользователей. Только тип и место.

### 3. Заодно — валидировать callback_data

Дешёвая обёртка вместо 15 правок:

```python
def parse_int(data: str, index: int) -> int | None:
    try:
        return int(data.split(":")[index])
    except (IndexError, ValueError):
        return None
```

Но это 15 правок. Приоритет — глобальный обработчик (он закрывает
все пути сразу, включая будущие). Валидация — отдельная задача.

## Как проверить

```python
async def test_global_error_handler_answers_callback():
    """Сбой в обработчике должен давать ответ, а не вечный спиннер.

    Раньше исключение уходило только в лог: cb.answer() не вызывался,
    и пользователь видел незакрытую кнопку.
    """
```

Вживую: отправить боту подделанный callback (например, через
`curl` к Bot API с `callback_query`) — должен прийти ответ
«⚠️ Что-то пошло не так».

## Риски

- **Двойной ответ.** Если обработчик уже успел ответить и потом упал,
  второй `answer()` вернёт `query is too old` — обёрнуто в `try`.
- **Спам админу.** Одна и та же ошибка в цикле даст много сообщений.
  Добавить простую дедупликацию по типу+месту (или переиспользовать
  `alerts.alert`, он уже умеет не повторяться).
- **Не скрыть ошибку.** Обработчик логирует `exc_info`, а не глотает.
