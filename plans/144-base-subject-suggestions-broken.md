# План 144: подсказки предметов в редакторе базы не работают

> **СДЕЛАНО 27.10.2026** (коммит `7a0e328`).
>
> `cb_edit_base` кладёт `suggestions` в state. Заодно проверен путь
> замен (`cb_sub_edit`) — там всё было верно.

**Приоритет:** средний. Староста видит кнопки, жмёт — получает
«Устарело». Выглядит как поломка.

**Трудоёмкость:** S (одна строка).

## Проблема

`cb_edit_base` (`editor.py:388`) получает подсказки и рисует их
кнопками:

```python
suggestions = await _subject_suggestions(repo, group)
await state.update_data(layer="base", weekday=weekday, parity=parity, para=para)
await state.set_state(EditorState.subject)
```

А `cb_subject_suggestion` (`:405`) берёт их **из FSM**:

```python
data = await state.get_data()
suggestions = data.get("suggestions") or []
idx = int(idx_s)
if idx >= len(suggestions):
    await cb.answer("Устарело", show_alert=True)
    return
```

**`suggestions` в `update_data` не передаётся** — ключа нет, вернётся
`None`, `[] or []` → `[]`, и `0 >= 0` → «Устарело».

## Проверил на живой группе

`_subject_suggestions("ДП-26")` отдаёт 6+ предметов:

```
Организация документооборота и документирование управленческ…
Деловая культура
Систематизация и организация оперативного хранения документо…
Архивное дело
Безопасность жизнедеятельности
История России
```

Кнопки **отрисуются** — они строятся из локальной переменной
(`_suggest_kb(suggestions, ...)`), а не из FSM. Поэтому староста их
видит и жмёт.

Дальше:

```
data.get("suggestions")  -> None
suggestions = None or [] -> []
idx=0 >= len([])=0       -> True
-> cb.answer("Устарело", show_alert=True)
```

**Ни одна подсказка в базовом расписании не работает.**

## Замена работает правильно — сравнение

`cb_edit_sub` (`:652`) делает то же самое, но **сохраняет список**:

```python
suggestions = await _subject_suggestions(repo, group)
await state.update_data(layer="sub", date=date_s, para=para, action=action,
                        suggestions=suggestions)   # <- вот это
await state.set_state(EditorState.subject)
```

Разница в одной строке. Значит замысел был, а в ветке базы его
потеряли.

## Почему это не всплыло

Редактор `ДП-26` — единственный, и правки шли через **замены**
(поверх дня), а не через базовое расписание. Проверил: `schedule_edit`
= **0 строк** за всё время. Ни один путь не использовался всерьёз.

## Что сделать

Добавить `suggestions` в `update_data`:

```python
await state.update_data(layer="base", weekday=weekday, parity=parity, para=para,
                        suggestions=suggestions)
```

## Попутно: обработчики подсказок без проверки прав

Оба обработчика — `cb_subject_suggestion` (`:402`) и
`cb_sub_subject_suggestion` (`:667`) — **не зовут `editor_group`**:

```python
@editor_router.callback_query(F.data.startswith("ed:sug:"))
async def cb_subject_suggestion(cb: CallbackQuery, repo: RequestsRepo, state: FSMContext):
    _, _, weekday_s, parity, para_s, idx_s = cb.data.split(":")
    data = await state.get_data()          # <- прав не проверяем
```

Все остальные обработчики редактора начинаются одинаково:

```python
group = await editor_group(repo, cb.from_user.id)
if not group:
    await cb.answer("Нет прав", show_alert=True)
    return
```

Проверил остальные 20+ обработчиков `editor.py` — проверка есть у всех,
кроме этих двух.

**Насколько это опасно:** сам по себе обработчик ничего не пишет — он
только кладёт `subject` в FSM. Но он **продолжает цепочку**: переводит
в `EditorState.teacher` и показывает следующий шаг. То есть человек
без прав может дойти до `_save_base`, а там проверка есть (`:441`):

```python
group = await editor_group(repo, event.from_user.id)
if not group:
    return
```

Сохранение не пройдёт. Но человек потратит время на ввод предмета,
преподавателя и кабинета — и **не получит ни ошибки, ни подтверждения**:
`_save_base` при отсутствии прав делает `return` молча.

## Что проверил и признал корректным

**`_suggest_kb` не падает на пустом списке.** Строит только кнопку
«Назад» — если у группы нет предметов, кнопок подсказок не будет, и
нажать нечего. Дефект проявляется только когда предметы есть.

**`_subject_suggestions` работает.** Проверил на `ДП-26` — отдаёт
реальные предметы из `base_lesson`.

**Цепочка замены цела.** `ed:ssug:` → `ed:sub_skip_teacher` →
`ed:sub_skip_room` → `_save_sub` — все шаги на месте, `suggestions`
сохраняются.

## Риски

- **Одна строка правки** — риск минимальный, `update_data` уже
  вызывается рядом.
- **Проверку прав в подсказках** добавить стоит, но это меняет
  поведение: сейчас человек без прав хотя бы видит шаг, после правки
  получит «Нет прав». Это правильнее, но заметнее.
