# План 040: уведомление о правке не показывает время пар

**Приоритет:** средний. Сообщение приходит заранее, но по нему нельзя
понять, во сколько приходить.

**Трудоёмкость:** S (~12 строк).

## Проблема

`tgbot/services/notify_edits.py:50`:

```python
def _slots_text(slots: list[Slot]) -> str:
    if not slots:
        return "Занятий нет 🙌"
    lines = []
    for s in slots:
        flag = " 🔄" if s.changed else ""
        lines.append(f"<b>{s.para})</b> {s.subject}{flag}")
        meta = " · ".join(x for x in (s.teacher, s.room) if x)
        if meta:
            lines.append(f"     {meta}")
    return "\n".join(lines)
```

Номер пары есть, **времени нет**. Отрендерил на реальных данных:

```
🔄 Изменение в расписании

📅 Вторник, 27.10 · группа ДП-26
2) Деловая культура
     Молчанова Н.А. · 410
3) Архивное дело 🔄
     Золотухина Н.Е. · 212
4) Физкультура

Проверь расписание командой /start
```

Для сравнения — то же в `format_day`:

```
2) 10:45–12:40  Деловая культура
```

## Почему это важно

Уведомление приходит **заранее**, пушем на телефон. Студент может быть
не в боте и не помнить сетку. Ему нужно знать, к которому часу идти.

Сетка звонков к тому же **не одна**:

```
п2: I_IV=10:45–12:40, II_III=10:45–12:20   <- 20 минут разницы
```

И понедельник отличается от остальных дней на всех парах:

```
п1: MONDAY=09:25–11:00, OTHER=09:00–10:35
п2: MONDAY=11:10–13:05, OTHER=10:45–12:40
п3: MONDAY=13:15–14:50, OTHER=12:50–14:25
п4: MONDAY=15:00–16:35, OTHER=14:35–16:10
п5: MONDAY=16:45–18:20, OTHER=16:20–17:55
п6: MONDAY=нет,        OTHER=18:05–19:40
```

То есть по одному номеру пары время не восстановить — нужно знать и
день, и курс.

## Что сделать

Передать в `_slots_text` звонки и контекст:

```python
async def _slots_text(repo, group, date, slots) -> str:
    bell, lunches = await repo.bell_schedule.get_context()
    dt = day_type_from_date(date)
    cg = course_group_from_group(group)
    lines = []
    for s in slots:
        bs = bell.get((dt, cg, s.para)) or bell.get((dt, "I_IV", s.para))
        when = f"{bs.start:%H:%M}–{bs.end:%H:%M}  " if bs else ""
        flag = " 🔄" if s.changed else ""
        lines.append(f"<b>{s.para})</b> {when}{s.subject}{flag}")
        ...
```

Либо, что проще и надёжнее — **не изобретать формат**, а взять
`format_day`:

```python
from common.schedule import format_day
text = format_day(date, slots, bell, lunches, DETAIL_BRIEF,
                  meta="teacher", show_rov=False)
```

Тогда уведомление будет выглядеть ровно как экран «Сегодня», к
которому студент привык, и рассинхрон форматов исчезнет сам.

**Но просто подставить нельзя — задублируется заголовок.**
`format_day` сам пишет `📅 Вторник, 27 октября`, а `notify_edits`
уже пишет `📅 Вторник, 27.10 · группа ДП-26`. Проверил:

```
🔄 Изменение в расписании

📅 Вторник, 27.10 · группа ДП-26
📅 Вторник, 27 октября          <- дубль

Занятий нет 🙌
```

Значит нужно убрать свой заголовок из `notify_group_about_edit` и
дописать группу иначе — например, отдельной строкой после дня:

```python
body = f"группа <b>{group}</b>\n" + format_day(...)
```

Либо оставить `_slots_text` и добавить в него время — тогда правка
локальная, но третья реализация форматирования дня остаётся.

**`format_day` возвращает `empty_day` при пустом списке**, а не
`"Занятий нет 🙌"` — это `📅 Вторник, 27 октября\n\nЗанятий нет 🙌`.
Строки не совпадают, это тоже надо учесть при замене.

**Второй вариант предпочтительнее:** `_slots_text` — это третья
реализация форматирования дня (после `format_day` и
`base_day_text` в `editor.py`). Чем меньше таких реализаций, тем
меньше мест, где забывают время.

## Проверено и признано корректным

**`bell.py` намеренно не показывает время.** Там текст такой:

```python
text = f"🔔 {l.para} пара · {l.subject}{mark}"
```

Но событие отправляется **в момент звонка** (`if t != now_min:
continue`), то есть студент получает его ровно тогда, когда время
наступило. Часы в тексте были бы избыточны. Это не баг.

**Поллер показывает время правильно.** `notify_new_schedule`
использует `format_day` с полным контекстом:

```python
text = format_day(
    date, lessons, bell, lunches, user.bell_detail,
    meta="group" if is_teacher else "teacher",
    show_rov=not is_teacher,
    group_course_group=gcg,
)
```

**Рассылка в чаты тоже корректна**, хотя вызывается короче:

```python
text = format_day(date, lessons, bell, lunches, "brief")
```

`group_course_group` не передан, но `format_day` вычисляет `cg` по
имени группы через `course_group_from_group`, а для `@vuz` это даёт
`VUZ`. «Разговоры о важном» тоже не появятся у вуза — внутри
`format_day` есть проверка `not is_vuz(lessons[0].group)`.

## Побочно: `/setgroup` не проверяет группу

`admin.py:384` — та же болезнь, что `/group` в плане 037:

```python
group = parts[1].strip().upper()
await repo.chats.set_group(message.chat.id, message.chat.title or "", group)
```

Ни проверки существования, ни нормализации. Если админ ошибётся в
букве, чат будет получать «Занятий нет 🙌» каждый день и никто не
поймёт почему. Сейчас `chats` на проде пуст (0 записей), так что
проблема потенциальная, но чинится там же, где 037.

## Риски

- **`format_day` требует `lessons` с `group`.** `get_day_slots` его
  проставляет, так что при вызове из `notify_group_about_edit`
  (`slots = await get_day_slots(repo, group, date)`) всё сходится.
- **`format_day` вернёт `empty_day` с заголовком**, а `_slots_text`
  возвращает только «Занятий нет 🙌» — строки не совпадают.
- **Дублирование «Проверь расписание командой /start»** останется —
  это подпись уведомления, а не часть дня.
