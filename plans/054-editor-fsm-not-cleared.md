# План 054: FSM редактора не очищается — правка повторяется на каждом сообщении

> **СДЕЛАНО 27.10.2026** (коммит `9df8ea4`).
>
> `state.clear()` в `_save_base` после `_rebuild`, симметрично
> `_save_sub`. Плюс очистка во всех шести навигационных обработчиках:
> `cb_base`, `cb_base_para_back`, `cb_subs`, `cb_sub_day_back`,
> `cb_preview`, `cb_log` — каждому добавлен параметр `state`.
>
> Третий уровень защиты из плана (`on_subject` проверяет наличие
> `weekday`/`date`) не делал: после правки состояние-сироту создать
> нечем, а лишняя ветка в горячем обработчике — только шум.

**Приоритет:** высокий для старост. Пара перезаписывается молча, без
подтверждения, от любого текста в чате.

**Трудоёмкость:** S (~6 строк).

## Проблема

`_save_base` (`editor.py:439`) сохраняет пару и **не вызывает
`state.clear()`**. Сравни с `_save_sub` (`editor.py:703`), где очистка
есть на строке 729:

```python
# _save_sub — правильно
    await repo.substitutions.set(...)
    await _rebuild(repo, date)
    await repo.edit_log.log(...)
    await state.clear()          # <- ЕСТЬ
```

```python
# _save_base — очистки нет
    await repo.base_lessons.upsert(...)
    await repo.edit_log.log(...)
    await _rebuild(repo)
    # ... уведомление, текст «Сохранено», ответ
    # state.clear() отсутствует
```

Единственная очистка в `_save_base` — в ветке ошибки, когда предмет
пустой (`:455`). При успешном сохранении состояние остаётся
`EditorState.room`.

## Что происходит

1. Староста жмёт «Изменить» на паре 3.
2. `cb_edit_base` ставит `state = {layer: "base", weekday, parity, para}`
   и `EditorState.subject`.
3. Вводит предмет → `on_subject` → `EditorState.teacher`.
4. Вводит преподавателя → `on_teacher` → `EditorState.room`.
5. Вводит кабинет → `on_room` → `_save_base` → **пара сохранена**.
6. `state` остался `EditorState.room`, данные всё ещё в `state.data`.
7. Староста пишет в чат **что угодно** — например, «спасибо».
8. `on_room` ловит это как кабинет, `_save_base` вызывается снова.
9. Пара 3 перезаписывается: `room = "спасибо"`.

Дальше каждое сообщение повторяет цикл. Причём `_rebuild` и рассылка
уведомлений срабатывают на каждое — то есть студенты группы получают
уведомление о правке при каждом случайном сообщении старосты.

## Второй вход в ту же дыру

`cb_base_para_back` (`editor.py:346`) — кнопка «Назад» на экране ввода
предмета — **не чистит состояние**:

```python
async def cb_base_para_back(cb, repo):
    group = await editor_group(repo, cb.from_user.id)
    if not group:
        await cb.answer("Нет прав", show_alert=True)
        return
    _, _, weekday_s, parity = cb.data.split(":")
    await _render_base_slots(cb, repo, group, int(weekday_s), parity)
    await cb.answer()
    # state.clear() нет
```

Сценарий: староста нажал «Изменить», потом передумал и нажал «Назад».
Он видит список пар, но `EditorState.subject` всё ещё активен. Любой
текст — `/start`, «привет», случайное нажатие — уходит в `on_subject`
как название предмета, и цепочка доходит до сохранения.

Очищает состояние только `cb_back` (`editor.py:278`) — главное меню
редактора. Остальные навигационные обработчики (`cb_base`, `cb_subs`,
`cb_preview`, `cb_log`, `cb_base_para_back`, `cb_sub_day_back`) — нет.

## Что сделать

**Одна строка в `_save_base`** после `_rebuild`, симметрично `_save_sub`:

```python
    await _rebuild(repo)
    await state.clear()
```

**Очистка во всех навигационных обработчиках.** Достаточно в каждом,
где вызывается `cb.message.edit_text` с переходом на другой экран:

```python
async def cb_base_para_back(cb, repo, state: FSMContext):
    ...
    await state.clear()
    await _render_base_slots(...)
```

`state` уже инжектится middleware — надо только добавить параметр.

**Третий уровень защиты** (по желанию): `on_subject` и `on_teacher`
проверяют, что в данных есть ожидаемые поля, и сбрасывают состояние,
если нет:

```python
@editor_router.message(EditorState.subject)
async def on_subject(message, repo, state):
    data = await state.get_data()
    if "weekday" not in data and "date" not in data:
        await state.clear()          # состояние-сирота
        return                        # пусть ответит any_text из user.py
    ...
```

## Почему это важно

Проверил прод: `schedule_edit` — **0 строк**. То есть редактор не
использовался ни разу за всё время. Значит баг ещё не навредил, но:

- в `schedule_editor` две записи, обе на группу `ДП-26` — доступ выдан
  (проверил: `494917175` = `virp0m`, владелец бота, и `1079347288` =
  `ERRIRS`; оба `role='student'`, оба в `ДП-26`);
- первый же староста, который начнёт править, попадёт в эту ловушку;
- повреждение тихое: пара перезаписывается, `edit_log` фиксирует каждую
  запись как отдельную правку, откатить можно только по одной за раз.

## Проверено и признано корректным

**Порядок роутеров правильный.** `tgbot/handlers/__init__.py`:

```python
routers_list = [admin_router, editor_router, user_router]
```

Комментарий в файле объясняет зачем: «editor_router идёт ДО user_router
— у пользователя есть catch-all `any_text`». Проверил `user.py:1023` —
`any_text` действительно ловит любой текст без проверки состояния.
При текущем порядке текстовый ввод старосты доходит до редактора.
Если кто-то переставит роутеры — редактор перестанет работать целиком.

**`_save_sub` очищает состояние правильно** — и в ветке ошибки (`:721`),
и после успеха (`:729`). С него и надо брать пример.

**`cb_back` очищает состояние** — единственный навигационный
обработчик, который это делает.

**Мёртвый код в `cb_log`** (`editor.py:812`):

```python
where = e.date.strftime("%d.%m") if e.date else \
    f"{WEEKDAY_SHORT[(e.para or 1) - 1] if False else ''}".strip()
if e.layer == "base":
    where = f"база/{e.para} пара"
elif e.layer == "sub":
    where = f"замена {e.date.strftime('%d.%m') if e.date else ''}/{e.para} пара"
```

`if False else ''` всегда даёт пустую строку, и результат тут же
перезаписывается в `if/elif`. Первое присваивание мёртвое целиком —
даже `e.date.strftime` не вычисляется. Убрать.

Побочно: если `e.para` окажется `None`, в журнале появится
«база/None пара». Сейчас в базе 0 записей, так что не проявлялось, но
`para` в модели допускает `NULL`.

## Риски

- **Добавление `state: FSMContext` в обработчики** меняет их сигнатуру.
  Middleware уже инжектит `state` — проверено по `cb_edit_base` и
  `cb_back`, где параметр есть. Значит правка механическая.
- **`state.clear()` в навигации сломает сценарий «вернуться и
  продолжить»** — но такого сценария нет: каждый экран начинает ввод
  заново через `cb_edit_base`.
- **Правка `_save_base` не чинит уже испорченные данные** — журнал
  пуст, так что чинить нечего.
