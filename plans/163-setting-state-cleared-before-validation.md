# План 163: «Попробуй ещё раз» не работает — состояние сбрасывается до проверки

> **СДЕЛАНО 28.10.2026.** Подтверждено: state.clear() стоял до проверки ввода в m_setting, все четыре настройки. Коммит bf5296b.

**Приоритет:** низкий. Настройка не сохранится неправильно, но текст
ответа врёт, и админ теряет введённое значение, не понимая почему.

**Трудоёмкость:** S (~3 строки — переставить).

## Что происходит

`m_setting` (`admin.py:973-987`) обрабатывает ввод всех настроек:

```python
async def m_setting(message: Message, repo: RequestsRepo, state: FSMContext):
    current = await state.get_state()
    item = next((s for s in SETTINGS.values() if s.state.state == current), None)
    await state.clear()                     # <- :980 ДО валидации
    if item is None:
        return
    try:
        value = item.parse(message.text.strip())
    except (ValueError, TypeError):
        await message.answer("Неверное значение. Попробуй ещё раз.")   # <- :985
        return
    for key, val in zip(item.keys, value):
        await repo.settings.set(key, val)
    await message.answer(item.ok.format(*value))
```

**`state.clear()` стоит на строке 980, а валидация — на 983.**
Если парсер бросил `ValueError`, состояние уже пусто.

## Что видит админ

```
1. /settings -> «Интервал опроса»
2. state = AdminState.set_poll
3. вводит «abc»
4. parse -> ValueError
5. state.clear() уже выполнен
6. ответ: «Неверное значение. Попробуй ещё раз.»
7. вводит «600» — и НИЧЕГО не происходит
```

Сообщение обещает повторить попытку, но следующее сообщение уже не
попадёт в `m_setting` — состояние пусто. Оно уйдёт дальше по цепочке
роутеров (`[admin_router, editor_router, user_router]`) в `any_text`
(`user.py:1022`), который ловит любой текст.

Админ видит что-то вроде «не понял» и не связывает это с настройкой,
которую только что пытался изменить.

## Почему это не то же, что план 054

[План 054](054-editor-fsm-not-cleared.md) — про `_save_base`
(`editor.py:439`), где `state.clear()` **отсутствует вообще**: правка
повторяется на каждом следующем сообщении.

Здесь обратная ошибка — очистка **слишком ранняя**. Один и тот же
вызов, три разных неправильных места:

```
editor.py:439  _save_base  — не очищен вообще      (план 054)
editor.py:703  _save_sub   — после сохранения      ПРАВИЛЬНО
admin.py:980   m_setting   — до валидации          этот план
```

## Что сделать

Перенести очистку после успешной проверки:

```python
async def m_setting(message: Message, repo: RequestsRepo, state: FSMContext):
    current = await state.get_state()
    item = next((s for s in SETTINGS.values() if s.state.state == current), None)
    if item is None:
        await state.clear()
        return
    try:
        value = item.parse(message.text.strip())
    except (ValueError, TypeError):
        # Состояние НЕ трогаем: «Попробуй ещё раз» должно работать.
        await message.answer("Неверное значение. Попробуй ещё раз.")
        return
    await state.clear()
    for key, val in zip(item.keys, value):
        await repo.settings.set(key, val)
    await message.answer(item.ok.format(*value))
```

Ветка `item is None` тоже чистит состояние — там продолжать нечего.

## Проверено и признал корректным

**Значение не сохраняется при ошибке.** `repo.settings.set` вызывается
только после успешного `parse`. Данные не портятся — страдает только
UX.

**`state.clear()` при `item is None`** нужен: если состояние есть, а
настройки с таким `state` нет (например после отката кода), висеть в
нём незачем.

**Кнопка «❌ Отмена» работает.** `cb_set_cancel:948` вызывает
`state.clear()` — из любого состояния есть выход, и он не зависит от
этого дефекта.

**Остальные настройки ведут себя так же.** Дефект общий для всех пяти:
`poll`, `rate`, `deadline`, `night`, `support` — все идут через
`m_setting`.

## Риски

- **Никаких.** Правка переставляет существующий вызов, поведение при
  успехе не меняется.
- **Тест:** после неверного ввода состояние должно остаться
  `AdminState.set_poll`, и следующее верное значение — сохраниться.
  Сейчас в `tests/` тестов на `m_setting` нет вообще (план 057).
