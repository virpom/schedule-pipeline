# План 045: `/setbell` ломает перерыв внутри пары и не знает про вуз

> **СДЕЛАНО 27.10.2026** (коммит `2d1dd3c`).
>
> **Баг 1:** `upsert` принимает `h1_end` и `h2_start`; формат команды
> получил необязательный третий отрезок
> (`10:45-11:30-11:55-12:40`). Два времени работают как раньше.
> Порядок проверяется: `start < h1_end <= h2_start < end`.
>
> **Баг 2** (сетка вуза) закрыт раньше — в плане 027 (`bb33868`):
> `VUZ` добавлен в `VALID_COURSE`.

**Приоритет:** средний. Команда админская и редкая, но после неё
расписание звонков становится неправильным для всех.

**Трудоёмкость:** S (~15 строк).

## Баг 1: `upsert` теряет перерыв между академическими часами

`infrastructure/database/repo/bell_schedule.py:78`:

```python
async def upsert(self, day_type, course_group, para, start, end) -> None:
    await self.session.execute(
        insert(BellSchedule)
        .values(
            day_type=day_type, course_group=course_group, para=para,
            start=start,
            h1_end=end,        # <- конец первого часа = конец пары
            h2_start=end,      # <- начало второго = конец пары
            end=end,
        )
        ...
```

Сигнатура принимает только `start` и `end` — перерыва в ней нет
вовсе. Значит `h1_end` и `h2_start` выставляются в `end`, и пара
превращается в сплошной блок.

**На проде это 38 пар из 39.** Проверил:

```
всего bell_schedule: 39
с перерывом (h1_end != h2_start): 38
```

То есть структура реальная, а `/setbell` её уничтожает.

### Что ломается

**Экран пары** (`_para_full`, `common/schedule.py:156`):

```python
if bs.h1_end == bs.h2_start:
    return f"{bs.start:%H:%M}–{bs.end:%H:%M}"     # сплошной
first = f"{bs.start:%H:%M}–{bs.h1_end:%H:%M}"
second = f"{bs.h2_start:%H:%M}–{bs.end:%H:%M}"
return f"{first} / {second}"
```

Было `09:00–09:45 / 09:50–10:35`, станет `09:00–10:35`. Студент с
`detail=full` потеряет разделение.

**Напоминания о перемене** (`bell.py:62`):

```python
if user.bell_mode == BELL_FULL and bp.h1_end != bp.h2_start:
    events.append((bp.h1_end, f"h1:{p}", "🔔 Перемена"))
    events.append((bp.h2_start, f"h2:{p}", "🔔 Перемена закончилась"))
```

После `/setbell` условие ложно — **напоминания исчезнут** у всех, у
кого `bell_mode=full`. На проде таких 7 человек.

## Баг 2: сетку вуза нельзя изменить

`admin.py:25`:

```python
VALID_COURSE = {"ALL", "I_IV", "II_III"}
```

А в `bell_schedule` на проде есть `VUZ` — 16 строк:

```
ALL      1
I_IV    11
II_III  11
VUZ     16
```

То есть сетка вуза существует и используется
(`course_group_from_group` для `@vuz` возвращает `VUZ`), но
`/setbell OTHER VUZ 1 09:00-10:35` отклонится с сообщением
«COURSE_GROUP: ALL|I_IV|II_III».

Сейчас сетку вуза можно поменять только руками в базе.

## Что сделать

**Часть 1 — принять перерыв в `upsert`.** Расширить сигнатуру, оставив
разумное поведение по умолчанию:

```python
async def upsert(self, day_type, course_group, para, start, end,
                 h1_end: datetime.time | None = None,
                 h2_start: datetime.time | None = None) -> None:
    h1 = h1_end or end
    h2 = h2_start or end
    await self.session.execute(
        insert(BellSchedule)
        .values(..., start=start, h1_end=h1, h2_start=h2, end=end)
        .on_conflict_do_update(..., set_=dict(start=start, h1_end=h1, h2_start=h2, end=end))
    )
```

**Часть 2 — формат команды.** Сейчас `/setbell DAY COURSE PARA HH:MM-HH:MM`.
Добавить необязательный третий отрезок:

```
/setbell OTHER I_IV 2 10:45-11:30-11:55-12:40
```

Четыре времени через дефис: `start-h1_end-h2_start-end`. Если задано
два — ведём себя как раньше (сплошная пара), чтобы не ломать привычку.

```python
times = time_s.split("-")
if len(times) == 2:
    start, end = map(datetime.time.fromisoformat, times)
    h1_end = h2_start = None
elif len(times) == 4:
    start, h1_end, h2_start, end = map(datetime.time.fromisoformat, times)
else:
    await message.answer("Время: HH:MM-HH:MM или HH:MM-HH:MM-HH:MM-HH:MM")
    return
```

**Часть 3 — пустить `VUZ`:**

```python
VALID_COURSE = {"ALL", "I_IV", "II_III", "VUZ"}
```

И в тексте подсказки добавить `VUZ`.

**Часть 4 — не терять перерыв при правке одной пары.** Сейчас
`/setbell` без перерыва перезапишет существующую структуру. Лучше
сохранить прежние `h1_end`/`h2_start`, если пара уже есть и новые не
заданы:

```python
old = await repo.bell_schedule.get(day_type, course_group, para)
h1 = h1_end or (old.h1_end if old else end)
h2 = h2_start or (old.h2_start if old else end)
```

Тогда `/setbell OTHER I_IV 2 10:45-12:40` поправит только границы, не
трогая перерыв.

**Метода `get` в `BellScheduleRepo` нет** — есть только `get_all`,
`get_lunches`, `get_context`, `upsert`, `seed_if_empty`. Придётся
добавить (~6 строк):

```python
async def get(self, day_type: str, course_group: str, para: int):
    result = await self.session.execute(
        select(BellSchedule).where(
            BellSchedule.day_type == day_type,
            BellSchedule.course_group == course_group,
            BellSchedule.para == para,
        ).limit(1)
    )
    return result.scalar_one_or_none()
```

## Проверено и признано корректным

**`seed_if_empty` перерыв сохраняет.** `DEFAULT_BELL` задаёт четыре
времени на пару, и вставка идёт через `datetime.time.fromisoformat` для
каждого поля отдельно. То есть начальные данные правильные — портит их
только `upsert`.

**`DEFAULT_BELL` совпадает с прод-данными.** Сверил MONDAY `I_IV`
п2: `11:10`, `11:55`, `12:20`, `13:05` — на проде те же значения.
Значит сид не разъезжался с реальностью.

**Обед (`DEFAULT_LUNCH`) не затронут** — у него своя таблица
`bell_lunch`, `upsert` её не касается.

**`/setbell` не проверяет `start < end`** — можно поставить
`10:00-09:00`, и `_para_full` покажет обратный интервал. Это отдельная
мелочь, но чинится там же одной строкой.

## Риски

- **Формат с четырьмя временами через дефис неоднозначен** для
  `datetime.time.fromisoformat` — придётся резать строку по `-`
  вручную. `10:45-11:30-11:55-12:40` даст ровно четыре части, но
  `10:45-12:40` — две, и обе валидны.
- **Сохранение прежнего перерыва может удивить**: админ поменял
  `start`, а `h1_end` остался старым и оказался раньше `start`. Нужна
  проверка `start <= h1_end <= h2_start <= end`.
- **`VUZ` в `VALID_COURSE` откроет `ALL`+`VUZ`** — сейчас `ALL`
  используется только для «Разговоров о важном» (п0). Если админ
  поставит `/setbell MONDAY VUZ 0 08:00-08:20`, это создаст линейку у
  вуза, которой там быть не должно. Проверка `para=0` только для
  `ALL` была бы уместна.
