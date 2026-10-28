# План 120: архив прошедших дней пишется, но его никто не читает

> **СДЕЛАНО 27.10.2026** (ранг 82, коммит `ff7f252` и правки после).
>
> `DaySnapshotRepo` получил `get`, `get_dates_for_group`,
> `get_dates_for_teacher`, `get_groups`, `get_teacher_from_group`.
> `_hist_page` объединяет даты из архива с `college_lesson`,
> `cb_hist_date` падает в архив, если в `college_lesson` пусто.
>
> Проверено на проде: у ДП-26 все 13 прошедших дат лежат только в
> архиве (`college_lesson` прошлых — 0), за 13.10 отдаётся 4 записи.

**Приоритет:** средний. Кнопка «📜 История» существует и обещает
архив, но читает другую таблицу. Три дня реальных данных недоступны.

**Трудоёмкость:** S (~15 строк).

## Проблема

`snapshot_past_days` (`notify_edits.py:61`) каждый час сохраняет
расписание прошедших дней в `day_snapshot`. Комментарий объясняет
зачем:

```python
"""Сохранить в архив расписание прошедших дней.

Учебный день кончился — фиксируем, что было (база + замены на тот
момент). Раньше этого не делалось: если сайт обновит файл задним
числом, история потерялась бы.
"""
```

Но `DaySnapshotRepo` (`infrastructure/database/repo/day_snapshot.py`)
содержит **только два метода**:

```python
async def save(self, date, group, lessons) -> None: ...
async def exists(self, date, group) -> bool: ...
```

**Метода чтения нет вообще.** Единственные вызовы во всём проекте:

```
notify_edits.py:76   if await repo.snapshots.exists(date, group):
notify_edits.py:81   await repo.snapshots.save(date, group, slots)
```

А кнопка «📜 История» (`user.py:765`) читает **`college_lesson`**:

```python
if _is_teacher(user):
    dates = await repo.college_lessons.get_dates_for_teacher(user.teacher_name)
else:
    dates = await repo.college_lessons.get_dates_for_group(user.group)
```

## Что это даёт — проверил на проде

```
college_lesson (прошлое): 02,03,05,06,07,08, 23,24 октября
day_snapshot:                              20,21,22,23,24 октября

ТОЛЬКО в архиве (недоступно в «Истории»):  20, 21, 22 октября
```

**Три учебных дня лежат в базе и недоступны.** Причём это ровно те дни,
которые `college_lesson` уже выбросил из окна материализации.

Проверил содержимое — данные полные:

```
2026-10-22  АТ-26:  [{"para":1,"subject":"Математика","teacher":"Багомедова У.М.",...}]
2026-10-22  ДОУ-24: [{"para":1,"subject":"Организация работы с электронными документами",...}]
```

234 снимка (403 всего, минус 5 дней × часть групп) записаны впустую.

## Почему это важно

`README.md:49` обещает пользователю:

```
| Прошедшие дни (архив из базы) | 📜 История |
```

`docs/ARCHITECTURE.md:170` тоже: `| day_snapshot | архив прошедших дней |`.

Студент нажимает «История», видит 23 и 24 октября — и всё. Дни 20–22
пропали, хотя они есть. Для вузовских групп ситуация хуже: у них
`college_lesson` материализуется вперёд, а назад заполняется только
по мере прошествия, поэтому архив — единственный надёжный источник.

## Что сделать

Добавить чтение в `DaySnapshotRepo`:

```python
async def get(self, date: datetime.date, group: str) -> list[dict]:
    result = await self.session.execute(
        select(DaySnapshot.payload).where(
            DaySnapshot.date == date, DaySnapshot.group == group)
    )
    raw = result.scalar_one_or_none()
    return json.loads(raw) if raw else []

async def get_dates(self, group: str) -> list[datetime.date]:
    result = await self.session.execute(
        select(DaySnapshot.date).where(DaySnapshot.group == group)
        .order_by(DaySnapshot.date)
    )
    return [d for (d,) in result.all()]
```

И в `_hist_page` (`user.py:765`) объединить два источника:

```python
live = await repo.college_lessons.get_dates_for_group(user.group)
archived = await repo.snapshots.get_dates(user.group)
dates = sorted(set(live) | set(archived))
```

При показе дня — сначала пробовать `college_lesson`, при пустом
результате падать на `day_snapshot`.

**Аккуратнее:** `payload` хранит `dict`, а не `Slot`. Для `format_day`
нужно обернуть:

```python
slots = [Slot(**d) for d in await repo.snapshots.get(date, group)]
```

`Slot` принимает `para`, `subject`, `teacher`, `room` — ровно те поля,
что пишет `save`.

## Проверено и признано корректным

**`snapshot_past_days` сохраняет верно.** Проверил: `get_day_slots`
даёт слоты с учётом замен на тот момент, `save` пишет `para`,
`subject`, `teacher`, `room` через `json.dumps`. `on_conflict_do_update`
по `(date, group)` не даёт дублей — подтверждено: `uc_day_snapshot`
в схеме.

**Воскресенья пропускаются правильно.** `if date.isoweekday() == 7:
continue`. Проверил: 25.10 — воскресенье, снимка нет, и это верно.

**Сегодняшний день не архивируется** — `range(1, days_back + 1)`
начинается с 1. Правильно: день ещё не кончился.

**Пустые дни не сохраняются** — `if not slots: continue`. Проверил:
пустых `payload` в базе нет.

**Место не проблема.** 403 строки, 117 504 символа payload, средний
291 символ. Прогноз: ~18 000 строк в год, ~4 МБ. Для SQLite это ничто.

**`get_groups()` вызывается трижды** (внутри цикла по дням,
`notify_edits.py:74`) — лишние два запроса. Замерил весь проход:
**0.29 с**. Оптимизировать не за чем, но если трогать файл — вынести
из цикла.

## Риски

- **`college_lesson` и `day_snapshot` могут расходиться.** Если сайт
  обновил файл задним числом, `college_lesson` покажет новую версию,
  а архив — ту, что была. Это и есть смысл архива, но пользователь
  должен понимать, что видит. Стоит помечать архивные дни.
- **`payload` не хранит `changed`, `action`, `comment`.** Отменённая
  пара в архиве будет выглядеть как обычная или исчезнет. Проверил:
  `save` пишет только четыре поля. Для истории это потеря, но
  восстанавливать её из архива нечем — данных нет.
