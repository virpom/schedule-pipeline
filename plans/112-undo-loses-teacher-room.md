# План 112: откат правки старосты восстанавливает пару без преподавателя и аудитории

**Приоритет:** средний. Редактор ни разу не использовался (0 записей в
`schedule_edit`), так что жертв нет. Но первый староста, который
удалит пару и передумает, получит полурaсписание.

**Трудоёмкость:** S (~4 строки).

## Проблема

`cb_del_base` (`editor.py:497`) при удалении пишет в журнал **только
предмет**:

```python
old_slot = next((l for l in lessons if l.para == para), None)
await repo.base_lessons.delete_slot(group, parity, weekday, para)
await repo.edit_log.log(
    group, "base", "delete", user_id=cb.from_user.id, para=para,
    old_value={"subject": old_slot.subject} if old_slot else None,   # <- только subject
)
```

`teacher` и `room` выбрасываются, хотя `old_slot` их содержит.

## Что происходит при откате

`cb_undo` (`editor.py:829`) разбирает запись:

```python
old = json.loads(last.old_value) if last.old_value else {}
new = json.loads(last.new_value) if last.new_value else {}
weekday, parity = new.get("weekday"), new.get("parity")

if last.action == "add":
    ...
elif old.get("subject"):
    await repo.base_lessons.upsert(
        group, parity, weekday, last.para, old["subject"],
        teacher=old.get("teacher", ""),        # <- пусто
        room=old.get("room", ""),              # <- пусто
        source="manual", updated_by=cb.from_user.id)
    msg = f"↩️ Возвращено: <b>{old['subject']}</b>"
else:
    # Пара была удалена — из журнала её содержимое не восстановить.
    msg = "↩️ Откат: пара была удалена (восстанови вручную)"
```

**Ветка `else` для удаления недостижима.** Условие
`elif old.get("subject")` истинно, потому что `cb_del_base` записал
`subject`. Значит откат пойдёт туда, восстановит пару с пустыми
`teacher` и `room` — и отрапортует «Возвращено: <b>Математика</b>».

Студент увидит:

```
📅 Понедельник, 26 октября

1) Математика
```

без преподавателя и кабинета. При этом `msg` утверждает, что всё
вернулось.

## Вторая проблема — в том же месте

`new.get("weekday")` и `new.get("parity")` берутся из `new_value`, а
`cb_del_base` **не передаёт `new_value` вовсе**:

```python
await repo.edit_log.log(
    group, "base", "delete", user_id=cb.from_user.id, para=para,
    old_value={...},
)
```

Значит `new` = `{}`, `weekday` и `parity` = `None`, и условие
`if weekday and parity:` **ложно**. Восстановление не произойдёт
вовсе — но `msg` всё равно скажет «Возвращено».

Проверил сигнатуру `log` (`schedule_edit.py:20`):

```python
async def log(self, group: str, layer: str, action: str,
              user_id: int | None = None, date: datetime.date | None = None,
              para: int | None = None, old_value=None, new_value=None) -> None:
```

`new_value` по умолчанию `None` → `_dump(None)` вернёт `""` →
`json.loads("")` упадёт... нет, `if last.new_value else {}` — пустая
строка ложна, вернётся `{}`.

**Итог — проверил на живом коде:**

```
_dump(None) = ''
new = {}
weekday=None  parity=None
if weekday and parity: -> False

old = {'subject': 'Математика'}
НЕ ВОССТАНОВИТ, но msg скажет «Возвращено»
```

**Откат удаления не делает ничего** — ни пары, ни преподавателя, ни
аудитории. И при этом отвечает старосте «↩️ Возвращено:
<b>Математика</b>». Он уверен, что всё вернул, и уходит.

Это хуже, чем просто потеря `teacher` и `room`: теряется вообще всё,
и молча.

## Что сделать

**Шаг 1 — сохранять слот целиком:**

```python
old_value={"subject": old_slot.subject,
           "teacher": old_slot.teacher,
           "room": old_slot.room} if old_slot else None,
```

**Шаг 2 — передавать `weekday` и `parity`**, иначе откат не знает
куда (это и есть причина, по которой он сейчас не срабатывает):

```python
await repo.edit_log.log(
    group, "base", "delete", user_id=cb.from_user.id, para=para,
    old_value={"subject": old_slot.subject, "teacher": old_slot.teacher,
               "room": old_slot.room} if old_slot else None,
    new_value={"weekday": weekday, "parity": parity},
)
```

Две правки, ~4 строки.

**Шаг 3 — пересобрать слой.** `cb_undo` не вызывает `_rebuild`, в
отличие от всех шести остальных мест правки:

```
474: await _rebuild(repo)          (сохранение базы)
513: await _rebuild(repo)          (удаление базы)
618: await _rebuild(repo, date)     (снятие замены)
635: await _rebuild(repo, date)     (сброс замены)
726: await _rebuild(repo, date)     (сохранение замены)
```

`cb_undo` — единственная без. Значит даже успешный откат не доедет до
студента, пока поллер не опросит сайт (до 5 минут, а при лежащем
сайте — никогда).

Добавить перед `await cb.answer(msg, ...)`:

```python
await _rebuild(repo)
```

## Проверено и признано корректным

**Ручные правки не затираются синхронизацией.** Проверил обе функции:

- `replace_base_lessons` (`sync_eios.py:58`) читает строки с
  `source != 'site'`, удаляет **только** `source='site'`, а ключи
  ручных пропускает через `manual_keys`.
- `replace_substitutions` (`sync_eios.py:111`) делает то же самое.

Это сделано правильно и с комментариями, объясняющими почему.

**`materialize_day` существует и работает.** `sync_eios.py:350`,
пересобирает один день. `_rebuild(repo, date)` вызывает его.

**Журнал сейчас пуст.** `schedule_edit` = 0 строк, `base_lesson` с
`source='manual'` = 0, `substitution` с `source='manual'` = 0. Весь
редактор ни разу не использовался, поэтому дефект никому не навредил.

**`cb_del_base` вызывает `_rebuild(repo)`** (`:513`) — сама правка
доходит до студента сразу. Проблема только в откате.

## Риски

- **`upsert` с `source="manual"` навсегда закрепит пару.** После
  отката строка получит `source='manual'`, и `replace_base_lessons`
  её больше не тронет — даже если сайт уберёт эту пару из файла.
  Это, возможно, и правильно (человек сознательно вернул), но стоит
  понимать: откат создаёт ручную правку, а не восстанавливает
  состояние «как было».
- **`old_slot` может быть `None`.** Тогда `old_value=None` →
  `_dump` вернёт `""` → `old` = `{}` → условие `elif old.get("subject")`
  ложно → сработает `else` с честным «восстанови вручную». Это
  правильное поведение, его ломать не надо.
