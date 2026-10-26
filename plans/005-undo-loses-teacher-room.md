# План 005: откат удаления не должен терять преподавателя и кабинет

**Приоритет:** пятый. Потеря данных при штатной операции «Откатить».

**Трудоёмкость:** S (две строки + 1 тест).

## Проблема

Оба обработчика пишут в журнал **только предмет**:

`tgbot/handlers/editor.py:468` (`cb_edit_base`):
```python
old_value={"subject": old_slot.subject} if old_slot else None,
```

`tgbot/handlers/editor.py:511` (`cb_del_base`):
```python
old_value={"subject": old_slot.subject} if old_slot else None,
```

А `cb_undo` (строка 854) восстанавливает так:

```python
elif old.get("subject"):
    await repo.base_lessons.upsert(
        group, parity, weekday, last.para, old["subject"],
        teacher=old.get("teacher", ""), room=old.get("room", ""),
        source="manual", updated_by=cb.from_user.id)
```

`old.get("teacher", "")` и `old.get("room", "")` **всегда** возвращают
пустую строку — этих ключей в журнале нет.

**Итог:** староста удаляет пару «Математический анализ · Кокошка И.П. ·
ауд. 214», жмёт «Откатить», и пара возвращается **без преподавателя и
без кабинета**. Студент видит неполное расписание.

## Почему это легко не заметить

- Тест `test_edit_undo.py` не зовёт `cb_undo` (см. план 004), поэтому
  не ловит.
- `upsert` с пустыми `teacher`/`room` не падает — просто пишет пустые
  строки.
- В интерфейсе откат отвечает «↩️ Возвращено: Математический анализ» —
  выглядит успешным.

## Что сделать

### 1. Писать все поля в `old_value`

Оба места заменить на:

```python
old_value={"subject": old_slot.subject,
           "teacher": old_slot.teacher,
           "room": old_slot.room} if old_slot else None,
```

Для `cb_edit_base` (строка 468) и `cb_del_base` (строка 511).

### 2. Для замен — писать `old_value` тоже

`cb_sub_edit` (строка 724) пишет только `new_value`, поэтому откат
замены всегда удаляет её, не восстанавливая прежнюю. Это ограничение
дизайна журнала (одна запись = одно состояние), но для замены
восстановление возможно и полезно:

```python
old_sub = await repo.substitutions.get_for_date(group, date)
old_slot = next((s for s in old_sub if s.para == para), None)
await repo.edit_log.log(
    group, "sub", "edit", ...,
    old_value={"action": old_slot.action, "subject": old_slot.subject,
               "teacher": old_slot.teacher, "room": old_slot.room} if old_slot else None,
    new_value={...})
```

И в `cb_undo`, в ветке `else`, восстановить вместо `delete`:

```python
else:
    old = json.loads(last.old_value) if last.old_value else {}
    if old.get("subject") or old.get("action") == SUB_CANCEL:
        await repo.substitutions.set(
            last.date, group, last.para,
            old.get("action", SUB_REPLACE),
            old.get("subject", ""), old.get("teacher", ""), old.get("room", ""),
            created_by=cb.from_user.id)
    else:
        await repo.substitutions.delete(last.date, group, last.para)
```

Проверить имена констант: `SUB_CANCEL`, `SUB_REPLACE` — свериться с
импортами в шапке `editor.py`.

### 3. Тест

Добавить в `tests/test_edit_undo.py`:

```python
def test_undo_restores_teacher_and_room():
    """Откат удаления возвращает пару целиком, а не только предмет.

    Раньше в журнал писался только subject, и после отката студент
    видел пару без преподавателя и аудитории.
    """
    # 1. base_lesson: ДП-26, чётная, Пн, 1 пара,
    #    subject="Математика", teacher="Кокошка И.П.", room="214"
    # 2. вызвать cb_del_base -> удалилось
    # 3. вызвать cb_undo
    # 4. прочитать base_lesson: teacher и room должны вернуться
```

## Как проверить

```bash
.venv/bin/python -m pytest tests/test_edit_undo.py -q
```

Вживую: удалить пару с преподавателем → «Откатить» → проверить, что
преподаватель на месте.

## Риски

- **Старые записи журнала.** У существующих записей `old_value` уже без
  `teacher`/`room`. После правки откат старых записей по-прежнему
  вернёт пустые поля. На проде `schedule_edit` — 0 строк, так что
  миграция не нужна.
- **`old_value` — JSON в `String(1024)`.** Проверено: три поля
  (`subject` 128 + `teacher` 128 + `room` 64) дают ~350 символов с
  разметкой. Запас 674. Миграция не нужна.
