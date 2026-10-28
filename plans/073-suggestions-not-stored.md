# План 073: подсказки предметов в базовом расписании не работают

> **СДЕЛАНО 27.10.2026** (коммит `7a0e328`).
>
> `cb_edit_base` кладёт `suggestions` в state. Заодно проверен путь
> замен (`cb_sub_edit`) — там всё было верно.

**Приоритет:** средний. Староста видит кнопки с названиями предметов,
нажимает — и получает «Устарело». Каждый раз.

**Трудоёмкость:** S (одна строка).

## Проблема

`cb_edit_base` (`editor.py:380`) строит подсказки и рисует кнопки, но
**не сохраняет список в FSM**:

```python
suggestions = await _subject_suggestions(repo, group)
await state.update_data(layer="base", weekday=weekday, parity=parity, para=para)
#                          ^^^ suggestions здесь НЕТ
await state.set_state(EditorState.subject)

await cb.message.edit_text(
    ...
    + _suggest_text(suggestions, "предметы группы"),
    reply_markup=_suggest_kb(suggestions, f"ed:sug:{weekday}:{parity}:{para}",
                             back=f"ed:bs:{weekday}:{parity}:{para}"),
)
```

`_suggest_kb` кладёт в `callback_data` **индекс**, а не текст:

```python
for i, item in enumerate(items[:limit]):
    rows.append([InlineKeyboardButton(text=item[:48],
                                      callback_data=f"{cb_prefix}:{i}")])
```

Обработчик `cb_subject_suggestion` (`editor.py:403`) достаёт список из
состояния:

```python
data = await state.get_data()
suggestions = data.get("suggestions") or []
idx = int(idx_s)
if idx >= len(suggestions):
    await cb.answer("Устарело", show_alert=True)
    return
```

`state.get_data()` вернёт `{}` для ключа `suggestions` — значит
`suggestions = []`, `len([]) == 0`, и условие `0 >= 0` истинно **всегда**.

**Итог:** любая подсказка в базовом расписании даёт всплывашку
«Устарело» и ничего не подставляет.

## Как это выглядит для старосты

```
✏️ Напиши название предмета.

предметы группы (нажми, чтобы подставить):
[ Организация документооборота ]
[ Документационное обеспечение ]
[ Архивное дело ]
[ ⬅️ Назад ]
```

Нажимает первую — «Устарело». Нажимает вторую — «Устарело». Кнопки
есть, но мертвы.

## Почему в заменах работает

`cb_sub_edit` (`editor.py:652`) делает то же самое, но **с** сохранением:

```python
suggestions = await _subject_suggestions(repo, group)
await state.update_data(layer="sub", date=date_s, para=para, action=action,
                        suggestions=suggestions)      # <- ЕСТЬ
```

И `cb_sub_subject_suggestion` (`editor.py:668`) читает
`data.get("suggestions")` — находит список, подставляет.

То есть механизм отлажен, просто в одной из двух веток забыли сохранить.

## Что сделать

Добавить `suggestions` в `update_data`:

```python
await state.update_data(layer="base", weekday=weekday, parity=parity,
                        para=para, suggestions=suggestions)
```

Одна строка. Всё остальное уже готово.

## Проверено и признано корректным

**`_suggest_text` и `_suggest_kb` не дублируют друг друга.** Первая
возвращает заголовок или пустую строку, вторая — клавиатуру. Если
подсказок нет, обе дают пустоту, и сообщение остаётся без лишних
элементов. Логика верная.

**Индекс в `callback_data` — правильное решение.** Текст предмета может
быть длиннее 64 байт (лимит `callback_data`), а `_suggest_kb` режет
подпись до 48 символов только в кнопке. Индекс короче и не ломается на
кириллице.

**`limit=5` в `_suggest_kb`.** Пять самых частых предметов группы —
достаточно, чтобы не превратить экран в список. Остальные можно
написать руками, поле ввода остаётся доступным.

**`_subject_suggestions` сортирует по частоте.** Считает вхождения по
всем трём чётностям (`PARITY_ODD`, `PARITY_EVEN`, `PARITY_ANY`) и
сортирует `-kv[1]`. Значит сверху будут предметы, которые у группы
реально идут каждую неделю, а не разовые.

## Риски

- **`state.get_data()` после `state.set_state()`** — порядок в
  `cb_edit_base` сейчас: сначала `update_data`, потом `set_state`. Это
  правильно: `set_state` не стирает данные. Но если кто-то переставит
  их местами, подсказки снова сломаются. Стоит держать `update_data`
  последним действием перед показом.
- **`suggestions` живёт в FSM до `clear()`.** `_save_base` не чистит
  состояние (это [план 054](054-editor-fsm-not-cleared.md)), поэтому
  список останется в данных после сохранения. Не страшно — он
  перезапишется при следующем заходе, — но после починки 054
  состояние будет чиститься, и порядок не сломается.
- **Тот же баг в других местах?** Проверил `grep -n "suggestions"
  tgbot/handlers/editor.py` — всего три места: `cb_edit_base` (не
  сохраняет), `cb_sub_edit` (сохраняет), два обработчика читают.
  Других веток нет.
