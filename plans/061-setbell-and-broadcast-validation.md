# План 061: интерактивная рассылка не проверяет группу

> **СДЕЛАНО 27.10.2026** (коммит `8bfa72f`), вторая половина.
>
> `m_group_broadcast` проверяет группу так же, как
> `/broadcast_group`: `get_by_group`, и при пустом ответе состояние
> не ставится.
>
> Находка 2, на которую план ссылался как на последствие, к этому
> моменту уже исправлена: в `cb_bc_send` `None` значит «всем», пустой
> список значит «никому». Опечатка стоила потерянного ввода, а не
> рассылки на всех. Первая половина (диапазон пары в `/setbell`)
> по-прежнему в [плане 027](027-setbell-no-validation.md).

**Приоритет:** средний. Ведёт прямо в находку 2 — необратимую.

**Трудоёмкость:** S (~4 строки).

> **Поправка.** Сначала в этом плане было две проблемы: `/setbell` без
> диапазона пары и рассылка без проверки группы. Первая **уже описана**
> в [плане 027](027-setbell-no-validation.md) — там и `para=99`, и
> `para=0`, и конец раньше начала, с разбором последствий для `bell.py`.
> Дублировать не нужно. Осталась только вторая.

## Два входа в рассылку группой — один проверяет, другой нет

`admin.py:525` — командный путь:

```python
async def broadcast_group_cmd(message, repo, config, state):
    ...
    group = parts[1].upper()
    users = await repo.users.get_by_group(group)
    if not users:
        await message.answer(f"В группе {group} никого нет")
        return                              # <- ПРОВЕРКА ЕСТЬ
    await _confirm_broadcast(...)
```

`admin.py:605` — интерактивный путь (кнопка → ввод группы):

```python
@admin_router.message(AdminState.set_group_broadcast)
async def m_group_broadcast(message: Message, state: FSMContext):
    group = message.text.strip().upper()
    await state.update_data(broadcast_target=group)
    await state.set_state(AdminState.set_broadcast)
    await message.answer(f"Введи текст сообщения для группы {group}:")
    # проверки НЕТ
```

Админ нажимает «🎓 Группе», вводит «МУСОР», и бот отвечает «Введи текст
сообщения для группы МУСОР» — то есть принимает опечатку за чистую
монету. Только после ввода текста, на экране подтверждения, он увидит
«Отправить **0** пользователям».

И тогда срабатывает находка 2: пустой список `broadcast_ids` в
`cb_bc_send` — falsy, уходит в `else`, и рассылка летит **всем 227**.

То есть интерактивный путь не просто неудобен — он ведёт прямо в
необратимую ошибку, а командный путь от неё защищён.

## Что сделать

**`m_group_broadcast` — та же проверка, что в командном пути:**

```python
@admin_router.message(AdminState.set_group_broadcast)
async def m_group_broadcast(message: Message, repo: RequestsRepo, state: FSMContext):
    group = message.text.strip().upper()
    if not await repo.users.get_by_group(group):
        await message.answer(f"В группе {group} никого нет. Проверь номер.")
        return
    ...
```

Нужно добавить `repo` в сигнатуру — middleware инжектит.

## Почему это важно

Интерактивная рассылка при опечатке в номере группы **отправляет
сообщение всем 227 пользователям**, и отозвать его нельзя. Командный
путь эту дыру уже закрывает — значит исправление не добавляет новую
логику, а выравнивает два входа.

## Проверено и признано корректным

**`m_setting` правильно ловит ошибки парсинга** (`admin.py:981`):

```python
try:
    value = item.parse(message.text.strip())
except (ValueError, TypeError):
    await message.answer("Неверное значение. Попробуй ещё раз.")
    return
```

`_num` бросает `ValueError` при выходе за диапазон, `_rate` — при
недопустимой скорости, `_night` — при неверном формате времени. Все
три корректны:

```python
def _num(text, lo, hi):
    value = int(text)          # ValueError на нечисле
    if not lo <= value <= hi:
        raise ValueError
```

Проверил `SETTINGS`: `poll` → 10–86400, `rate` → 0–30, `deadline` →
0–23. Границы разумные.

**`_spawn` корректен.** Проверил:

```python
def _spawn(coro) -> None:
    task = asyncio.create_task(coro)
    _background.add(task)          # держим ссылку — иначе GC убьёт задачу
    def _done(t):
        _background.discard(t)
        if not t.cancelled() and t.exception() is not None:
            logging.exception("фоновая рассылка упала", exc_info=t.exception())
    task.add_done_callback(_done)
```

Ссылка сохраняется в множестве (без этого задача может быть собрана
сборщиком мусора), ошибка логируется. Правильно.

**`_target_users` возвращает понятную подпись** — «преподавателям»,
«пользователям», «в группе X». Это попадает в подтверждение, так что
админ видит, кому шлёт.

## Риски

- **Добавление `repo` в `m_group_broadcast`** меняет сигнатуру, но
  middleware инжектит — безопасно.
- **Находка 2 всё равно остаётся.** Даже с проверкой группы пустой
  список может прийти иначе (например, группу удалили между выбором и
  отправкой). `cb_bc_send` надо чинить отдельно: `if ids is None`, а
  не `if ids`.
