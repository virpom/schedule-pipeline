# План 142: откат стирает преподавателя, а для замены — предыдущую замену

> **СДЕЛАНО 27.10.2026** (коммит `0101056`).
>
> Оба дефекта закрыты, как и предлагалось. `_save_base` и `cb_del_base`
> кладут в `old_value` все три поля. `_save_sub` читает прежнюю замену
> **до** upsert-а и пишет её в `old_value`, `cb_undo` восстанавливает
> через `set()`, а `delete()` остался только веткой «замены не было».
>
> Добавлено сверх плана: `_rebuild(repo, last.date)` после отката
> замены. Без него студент видел результат только после следующего
> опроса поллера — до пяти минут, а если сайт лежал, то никогда.
>
> Проверено на копии прод-базы: `teacher` заполнен у 2659 из 2659 пар,
> то есть до правки каждый откат базовой пары стирал преподавателя.

**Приоритет:** высокий. `teacher` заполнен у **100%** пар (2659 из
2659), и откат его обнуляет молча.

**Трудоёмкость:** S (~4 строки).

## Проблема 1: журнал не хранит преподавателя

`_save_base` (`editor.py:466`) пишет в журнал только предмет:

```python
await repo.edit_log.log(
    group, "base", "edit" if old_slot else "add", user_id=event.from_user.id,
    para=para,
    old_value={"subject": old_slot.subject} if old_slot else None,
    ...
)
```

А `cb_undo` (`:851`) восстанавливает все три поля:

```python
elif old.get("subject"):
    if weekday and parity:
        await repo.base_lessons.upsert(
            group, parity, weekday, last.para, old["subject"],
            teacher=old.get("teacher", ""), room=old.get("room", ""),
            source="manual", updated_by=cb.from_user.id)
```

`old.get("teacher", "")` вернёт **пустую строку** — в словаре её нет.

## Что это значит

Взял `ДП-26`, среда, чётная неделя:

```
п2  История России          teacher='Куранова Е.И.'   room=''
п3  Физическая культура     teacher='Рамазанов Т.М.'  room=''
п4  Основы делопроизводства teacher='Молчанова Н.А.'  room=''
```

Староста меняет п2 с «Истории России» на что-то другое, потом жмёт
«Откатить». Восстановится:

```
п2  История России   teacher=''   room=''
```

**Преподаватель пропал.** В расписании появится пара без того, кто её
ведёт.

## Масштаб

```
base_lesson: 2659 строк
  с teacher: 2659 (100%)
  с room:       0 (0%)
```

То есть **каждый** откат базовой пары стирает преподавателя. `room`
пока пуст везде, поэтому по нему потерь нет — но код его тоже не
сохраняет, и как только аудитории начнут заполнять, они будут
пропадать так же.

## Проблема 2: откат замены не возвращает предыдущую

`_save_sub` (`:728`) пишет в журнал **только `new_value`**:

```python
await repo.edit_log.log(group, "sub", "edit", user_id=event.from_user.id,
                        date=date, para=para, new_value={
                            "action": action, "subject": subject,
                            "teacher": teacher, "room": room})
```

`old_value` не передаётся — остаётся `NULL`.

`cb_undo` для замены (`:866`):

```python
else:
    await repo.substitutions.delete(last.date, group, last.para)
    msg = "↩️ Замена снята"
```

Просто **удаляет строку**.

## Когда это верно, а когда нет

**Верно**, если замены до правки не было: удалили — и снова видна
базовая пара. Это основной случай.

**Неверно**, если поверх уже была замена. `SubstitutionRepo.set`
(`substitution.py:28`) делает upsert по `(date, group, para)`:

```python
.on_conflict_do_update(
    index_elements=["date", "group", "para"],
    set_=dict(action=action, subject=subject, ...),
)
```

То есть **перезаписывает** прежнюю. Сценарий:

```
1. Староста ставит замену А на 27.10, п4
2. Замечает ошибку, ставит замену Б на ту же пару
   -> set() перезаписал А, в журнале две записи "edit"
3. Жмёт «Откатить»
   -> delete() убрал Б
   -> А тоже нет — она была перезаписана ещё на шаге 2
   -> студент видит базовую пару вместо А
```

Данные не восстанавливаются, потому что их нигде нет.

## Что сделать

**1. Сохранять полный слот в `old_value`:**

```python
old_value={"subject": old_slot.subject,
           "teacher": old_slot.teacher,
           "room": old_slot.room} if old_slot else None,
```

То же в `cb_del_base` (`:511`).

**2. В `_save_sub` читать прежнюю замену и писать её в `old_value`:**

```python
before = await repo.substitutions.get_for_date(group, date)
old_sub = next((s for s in before if s.para == para), None)
await repo.substitutions.set(...)
await repo.edit_log.log(..., 
    old_value={"action": old_sub.action, "subject": old_sub.subject,
               "teacher": old_sub.teacher, "room": old_sub.room} if old_sub else None,
    new_value={...})
```

**3. В `cb_undo` для замены восстанавливать, а не удалять:**

```python
else:
    old = json.loads(last.old_value) if last.old_value else None
    if old and old.get("subject"):
        await repo.substitutions.set(last.date, group, last.para,
                                     old["action"], old["subject"],
                                     old["teacher"], old["room"],
                                     created_by=cb.from_user.id)
        msg = "↩️ Предыдущая замена восстановлена"
    else:
        await repo.substitutions.delete(last.date, group, last.para)
        msg = "↩️ Замена снята"
```

## Что проверил и признал корректным

**`_save_base` пишет `"add"` или `"edit"` правильно.** Проверил
`:467`: `"edit" if old_slot else "add"` — если пары не было, это
добавление. `cb_undo` для `"add"` вызывает `delete_slot`, что верно:
возвращать нечего.

**`delete_slot` вызывается с правильными аргументами.** Проверил
сигнатуру `base_lesson.py:92`: `delete_slot(group, parity, weekday,
para)` — совпадает с вызовом `:846`.

**`upsert` не создаёт дубль при откате.** `on_conflict_do_update` по
`(group, parity, weekday, para)` — строка перезапишется, не
задвоится.

**`no_lessons` — мёртвая таблица** (из плана 141), к этому дефекту
отношения не имеет.

## Риски

- **`old_value` обрезается до 1024 символов** (`_dump`). На три поля
  хватает с запасом, но если когда-нибудь добавят `comment`, стоит
  проверить.
- **Правка `_save_sub` требует лишнего запроса** — `get_for_date` перед
  `set`. Он дешёвый (1.27 мс по замеру), на интерактивную правку
  влияния нет.
- **Откат `"delete"`** (пара была удалена) по-прежнему не восстановит
  содержимое: в журнале для `"delete"` есть `old_value`, но `cb_undo`
  в эту ветку не заходит — он смотрит только `last.action == "add"` и
  `old.get("subject")`. Проверил: `"delete"` пишет `old_value`, значит
  восстановить можно — но это отдельная правка, здесь не трогаю.
