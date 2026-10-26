# План 145: правка базовой пары через «Пропустить» падает с `KeyError`

> **СДЕЛАНО 27.10.2026** (коммит `0101056`).
>
> `on_teacher` теперь выбирает колбэк по слою — ровно тот сниппет, что
> был в плане. `ed:skip_room` ведёт в `_save_base`, `ed:sub_skip_room` в
> `_save_sub`.
>
> Проверено: `_save_sub` действительно читает `data["date"]` первой
> строкой, а у базовой правки в FSM только `weekday` и `parity` — то
> есть `KeyError` был гарантирован на каждом таком проходе.

**Приоритет:** высокий. Правка теряется целиком, староста не получает
ни ошибки, ни подтверждения.

**Трудоёмкость:** S (одна строка).

## Проблема

`on_teacher` (`editor.py:948`) показывает кнопку «Пропустить» для
кабинета — и **всегда** с колбэком ветки замен:

```python
@editor_router.message(EditorState.teacher)
async def on_teacher(message: Message, repo: RequestsRepo, state: FSMContext):
    await state.update_data(teacher=(message.text or "").strip())
    await message.answer(
        f"{EDITOR_TITLE}\n\n🚪 <b>Кабинет</b> или «Пропустить».",
        reply_markup=_skip_kb("ed:sub_skip_room"),   # <- всегда sub
    )
    await state.set_state(EditorState.room)
```

А `cb_sub_skip_room` (`:697`) вызывает **`_save_sub`**:

```python
@editor_router.callback_query(F.data == "ed:sub_skip_room")
async def cb_sub_skip_room(cb: CallbackQuery, repo: RequestsRepo, state: FSMContext):
    await state.update_data(room="")
    await _save_sub(cb, repo, state, via_cb=True)
```

`_save_sub` (`:707`) первым делом читает дату:

```python
date = datetime.date.fromisoformat(data["date"])
```

**У базовой правки даты нет** — она повторяется каждую неделю, в FSM
лежат только `weekday` и `parity`. Значит `data["date"]` →
**`KeyError`**.

## Полный сценарий

```
1. Староста: «Редактор» → «Базовое расписание» → Среда → Чётная → п2
   -> cb_edit_base
   state: layer="base", weekday=3, parity="even", para=2
   (date не ставится — база без даты)

2. Вводит предмет «Архивное дело» -> on_subject
   state: subject="Архивное дело"
   кнопка: ed:skip_teacher  (проверка layer=="sub" — верная)

3. Вводит преподавателя «Золотухина Н.Е.» -> on_teacher
   state: teacher="Золотухина Н.Е."
   кнопка: ed:sub_skip_room   <- ЗДЕСЬ ОШИБКА

4. Жмёт «Пропустить» -> cb_sub_skip_room
   -> _save_sub(...)

5. _save_sub:707
   date = datetime.date.fromisoformat(data["date"])
   KeyError: 'date'
```

## Что видит староста

**Ничего.** Глобального обработчика ошибок нет — проверил `main.py`,
там только `DatabaseMiddleware`. Исключение уходит в aiogram, тот
логирует и глотает.

Правка не сохранена, сообщения об ошибке нет. Староста видит, что бот
«не ответил», и жмёт ещё раз — но состояние уже сдвинуто, и он
вернётся в начало.

## Почему это не всплыло

Проверил логи контейнера за 11 часов:

```
'KeyError'          -> 0
"KeyError: 'date'"  -> 0
ERROR               -> 8, все TelegramForbiddenError
```

Восемь ошибок — известные блокировки бота (план 099). Путь с
`KeyError` **не использовался**, потому что староста правил только
замены, а не базу. Проверил `schedule_edit`: **0 строк** за всё время.

## Как должно быть

`on_subject` (`:938`) уже делает правильно — выбирает колбэк по слою:

```python
reply_markup=_skip_kb("ed:sub_skip_teacher" if data.get("layer") == "sub"
                      else "ed:skip_teacher"),
```

`on_teacher` этой проверки лишён. Надо так же:

```python
data = await state.get_data()
await message.answer(
    f"{EDITOR_TITLE}\n\n🚪 <b>Кабинет</b> или «Пропустить».",
    reply_markup=_skip_kb("ed:sub_skip_room" if data.get("layer") == "sub"
                          else "ed:skip_room"),
)
```

## Второй путь к тому же падению

Даже если староста **введёт кабинет текстом**, `on_room` (`:957`)
разбирает слой правильно:

```python
if data.get("layer") == "sub":
    await _save_sub(message, repo, state, via_cb=False)
else:
    await _save_base(message, repo, state, via_cb=False)
```

Значит текстовый ввод кабинета работает. Ломается **только кнопка
«Пропустить»** — то есть самый вероятный путь: кабинет часто пустой.

## Что проверил и признал корректным

**`on_subject` выбирает колбэк верно.** Проверил `:938`: `layer == "sub"`
→ `ed:sub_skip_teacher`, иначе `ed:skip_teacher`. Обе ветки
обрабатываются своими функциями (`:433` и `:697`).

**`cb_skip_teacher` (`:419`) ставит `teacher=""`** и ведёт в
`EditorState.room` с кнопкой `ed:skip_room` — верная ветка.

**`cb_skip_room` (`:433`) зовёт `_save_base`** — верно.

**Текстовый ввод кабинета не ломается.** `on_room:957` разбирает слой.

**Другие обработчики редактора не имеют такой путаницы.** Проверил все
`_skip_kb` и `cancel_kb` — колбэки подставляются по слою везде, кроме
`on_teacher`.

## Риски

- **Одна строка правки.** Риск минимальный: `state.get_data()` уже
  вызывается в соседних обработчиках.
- **Тесты не покрывают редактор.** Проверил: из 185 тестов ни один не
  зовёт `_save_base` или `_save_sub` — поэтому дефект и не поймали.
  Стоит добавить тест на выбор колбэка по `layer`.
