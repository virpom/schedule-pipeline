# План 002: рассылка «группе» без подписчиков не должна уходить всем

> **СДЕЛАНО 27.10.2026** (коммит `068e576`).
>
> `ids is None` вместо falsy-проверки: пустой список теперь значит «никого», а не «всем». Тест `tests/test_broadcast_targets.py`.

**Приоритет:** второй. Ошибка необратима: сообщение уходит 227 людям,
и отозвать его нельзя.

**Трудоёмкость:** S (одна строка + 1 тест).

## Проблема

`tgbot/handlers/admin.py:686`:

```python
items = [(uid, text) for uid in ids] if ids else [(u.id, text) for u in await repo.users.get_all()]
```

`ids` — это `broadcast_ids` из FSM-состояния. Ставится в
`_confirm_broadcast` (строка 470):

```python
await state.update_data(broadcast_text=text, broadcast_ids=[u.id for u in users])
```

Если админ выбрал группу без подписчиков, `users` пуст, значит
`broadcast_ids = []`. Пустой список — falsy, поэтому срабатывает ветка
`else`, и рассылка уходит **всем**.

При этом подтверждение показывает «Отправить **0** пользователям» и кнопку
«✅ Отправить» — админ нажимает, ожидая, что не уйдёт ничего.

**Проверено на боевой БД.** `get_by_group` (`repo/user.py:175`) фильтрует
только по `User.group == group` — подписка не проверяется:

```python
cond = User.group.is_(None) if group is None else (User.group == group)
```

Поэтому считать надо группы, где **нет ни одного пользователя** с такой
группой. Таких **8 из 37**:

```
ПРф-23, ПРф-24, ПСО-23, СМф-23, ТЭф-23, ЭК-24, ЭОф-23, ЮР-24А
```

Раньше в этом плане стояло «10 из 37 без подписчиков» — я пересчитал:
без подписчиков действительно 9 групп (`СМф-24` и `ЭК-23` добавляются),
но `get_by_group` их вернёт, потому что пользователи там есть, просто
отписались. Для срабатывания бага нужен пустой список, то есть 8 групп.

Путь достижим в любой момент.

Команда `/broadcast_group` защищена (`if not users: return`), а
интерактивный путь через меню — нет.

## Что сделать

### 1. Разделить «нет списка» и «пустой список»

В `admin.py:686` заменить:

```python
items = [(uid, text) for uid in ids] if ids else [(u.id, text) for u in await repo.users.get_all()]
```

на:

```python
if ids is None:          # состояние потеряно — рассылаем всем
    ids = [u.id for u in await repo.users.get_all()]
items = [(uid, text) for uid in ids]
```

Теперь `[]` (группа без подписчиков) остаётся пустым списком, а `None`
(состояние не задано) — по-прежнему «всем».

### 2. Не давать нажать «Отправить» при нуле получателей

В `_confirm_broadcast` (строка 467), перед `await message.answer(...)`:

```python
if not users:
    await message.answer(f"В выбранной аудитории ({label}) никого нет — рассылать некому.")
    await state.clear()
    return
```

Это повторяет поведение `/broadcast_group`, который уже так делает
(строка 533). Одна проверка вместо двух разных поведений.

### 3. Добавить тест

Новый файл `tests/test_broadcast_targets.py` — по образцу
`tests/test_admin_stats.py` (он уже поднимает БД и зовёт обработчики).

```python
def test_broadcast_to_empty_group_sends_nothing():
    """Группа без подписчиков не должна превращаться в «всем».

    Раньше пустой broadcast_ids — falsy — уводил рассылку на всех
    пользователей. Админ видел «0 получателей» и жал «Отправить».
    """
    async def scenario():
        engine, pool = await make_env()
        try:
            async with pool() as db:
                repo = RequestsRepo(db)
                # три пользователя в разных группах
                ...
                users = await repo.users.get_by_group("ПУСТАЯ-ГРУППА")
                assert users == []
                # ключевая проверка: пустой список не должен
                # разворачиваться в get_all()
        finally:
            await engine.dispose()
    run(scenario())
```

Тест должен проверять именно **решение**, а не `send_message`. Проще
всего вынести выбор получателей в чистую функцию и тестировать её:

```python
def _resolve_targets(ids: list[int] | None, all_ids: list[int]) -> list[int]:
    return all_ids if ids is None else ids
```

Тогда тест — три ассерта без БД и без бота.

## Как проверить

```bash
.venv/bin/python -m pytest tests/test_broadcast_targets.py -q
```

Вживую: зайти в админку → «Рассылка» → «Группе» → выбрать `ПРф-23`
(ноль подписчиков). Ожидаемо: бот отвечает «никого нет», кнопки
«Отправить» нет.

## Риски

- **Не сломать рассылку всем.** Путь «👥 Всем» ставит `broadcast_ids`
  через `_confirm_broadcast` с `users=get_all()`, то есть непустой
  список. `None` возникает только если состояние потерялось (рестарт
  бота при `MemoryStorage`) — тогда поведение «всем» сохраняется.
- **`MemoryStorage`**: состояние теряется при рестарте, поэтому
  `ids is None` — реальный сценарий, и запасная ветка нужна.
