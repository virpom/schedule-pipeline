# План 066: уведомление о правке базы не говорит, что изменилось

**Приоритет:** средний. Студент получает пуш, открывает расписание и не
понимает, что искать.

**Трудоёмкость:** S (~15 строк).

## Проблема

`editor.py:478` — правка базы:

```python
notified = await notify_group_about_edit(
    event.bot, repo, group, None, event.from_user.id)
```

Четвёртый аргумент — `date=None`. В `notify_edits.py:31`:

```python
if date is None:
    header = "✏️ <b>Изменено базовое расписание</b>"
    body = f"Группа <b>{group}</b>"
else:
    header = "🔄 <b>Изменение в расписании</b>"
    slots = await get_day_slots(repo, group, date)
    body = f"📅 <b>{_fmt_day(date)}</b> · группа <b>{group}</b>\n"
    body += _slots_text(slots)
```

При `date=None` студент получает ровно это:

```
✏️ Изменено базовое расписание

Группа ДП-26

Проверь расписание командой /start
```

**Ни что изменилось, ни когда, ни какая пара.** Студент должен открыть
расписание и сравнить с памятью.

При правке замены (`_save_sub`, `editor.py:735`) всё наоборот — дата
передаётся, и сообщение показывает список пар с флагами `🔄`.

## Почему это не оправдано

`date=None` логичен: правка базы повторяется каждую неделю, у неё нет
одной даты. Нельзя написать «📅 Ср 28.10» — таких сред много.

Но это объясняет отсутствие **даты**, а не отсутствие **содержания**.
Данные, что именно поменялось, у вызывающего есть:

```python
weekday = data["weekday"]
parity = data["parity"]
para = data["para"]
subject = (data.get("subject") or "").strip()
teacher = (data.get("teacher") or "").strip()
room = (data.get("room") or "").strip()
```

Всё это лежит в FSM на момент вызова. Более того — сразу после
уведомления `_save_base` собирает полный текст **для старосты**:

```python
lessons = await repo.base_lessons.get_day(group, weekday, parity)
slots = [Slot(l.para, l.subject, l.teacher, l.room) for l in lessons]
text = ("✅ <b>Сохранено</b>"
        ...
        f"{WEEKDAY_FULL[weekday - 1]}, {PARITY_LABELS.get(parity, parity)} неделя, "
        f"{para} пара → <b>{subject}</b>\n\n" + base_day_text(group, weekday, parity, slots))
```

То есть староста видит «Среда, чётная неделя, 3 пара → Физика» и весь
день целиком. Студент — «Группа ДП-26».

## Что сделать

Передать то, что известно. Проще всего — готовую строку описания:

```python
# notify_edits.py
async def notify_group_about_edit(
        bot: Bot, repo: RequestsRepo, group: str, date: datetime.date | None,
        author_id: int | None, rate: float = 20.0,
        change: str = "") -> int:
    ...
    if date is None:
        header = "✏️ <b>Изменено базовое расписание</b>"
        body = f"Группа <b>{group}</b>"
        if change:
            body += f"\n{change}"
```

И в `_save_base`:

```python
change = (f"{WEEKDAY_FULL[weekday - 1]}, {PARITY_LABELS.get(parity, parity)} неделя, "
          f"{para} пара → <b>{subject}</b>")
notified = await notify_group_about_edit(
    event.bot, repo, group, None, event.from_user.id, change=change)
```

Результат:

```
✏️ Изменено базовое расписание

Группа ДП-26
Среда, чётная неделя, 3 пара → Физика
```

Этого достаточно, чтобы студент понял, куда смотреть. Преподавателя и
кабинет можно добавить той же строкой, если нужно.

**Альтернатива — показывать весь день.** Для `date=None` нельзя взять
конкретную дату, но можно взять ближайшую подходящую:

```python
# ближайшая среда нужной чётности
```

Это уже сложнее и может показать не то (правка была «на будущее», а
ближайшая среда — завтра). Проще передать описание.

## Проверено и признано корректным

**`SubstitutionRepo.set` правильно сбрасывает детали при отмене.**
Проверил `on_conflict_do_update`:

```python
set_=dict(action=action, subject=subject, teacher=teacher, room=room, ...)
```

Вызов для отмены (`editor.py:613`) не передаёт `subject`/`teacher`/`room`,
значит они по умолчанию `""`. Для отменённой пары это верно — деталей
нет.

**`snapshot_past_days` правильно пропускает воскресенье** (`if
date.isoweekday() == 7: continue`) и не перезаписывает существующие
снимки (`if await repo.snapshots.exists(date, group): continue`). Это
сохраняет историю от перезаписи задним числом — ровно то, что обещает
докстринг.

**`notify_group_about_edit` исключает автора** из получателей:

```python
targets = [u.id for u in subscribers if u.id != author_id]
```

Староста не получает пуш о своей же правке. Верно.

**Рассылка только подписчикам группы**, а не всем 227:

```python
subscribers = await repo.users.get_subscribed_by_group(group)
```

Верно — комментарий в модуле это и обещает.

**`_slots_text` помечает изменённые пары флагом `🔄`** через
`s.changed`. Работает: `get_day_slots` выставляет `changed` для пар из
замен.

## Связанные находки

- **40** — уведомление не показывает время пар (`_slots_text` без
  звонков). Этот план — про **содержание правки базы**, находка 40 —
  про **время в списке пар**. Пересекаются, но чинятся в разных местах:
  40 в `_slots_text`, этот — в ветке `date is None`.
- **21** — `notify_edits` без тестов. Обе правки стоит покрыть.

## Риски

- **Новый параметр `change`** меняет сигнатуру. Два вызова
  (`editor.py:478`, `:735`), оба в этом же файле. Второй может не
  передавать — дефолт `""`.
- **HTML в `change`.** `subject` приходит от старосты и **не
  экранируется** (находка 66). Если в предмете будет `<`, сообщение не
  отправится. Чинить вместе с 66.
- **Длина.** `change` — одна строка, до лимита далеко.
