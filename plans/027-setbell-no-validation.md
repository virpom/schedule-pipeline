# План 027: `/setbell` принимает бессмысленные звонки

**Приоритет:** низкий. Админская команда, портит только сетку звонков.

**Трудоёмкость:** S (~12 строк).

## Проблема

`admin.py:701`:

```python
day_type, course_group, para_s, time_s = parts[1].upper(), parts[2].upper(), parts[3], parts[4]

if day_type not in VALID_DAY or course_group not in VALID_COURSE:
    await message.answer("DAY_TYPE: MONDAY|OTHER, COURSE_GROUP: ALL|I_IV|II_III")
    return

try:
    para = int(para_s)
    start_s, end_s = time_s.split("-")
    start = datetime.time.fromisoformat(start_s)
    end = datetime.time.fromisoformat(end_s)
except ValueError:
    ...
```

Проверяется формат, но не смысл. Принимается всё:

| Ввод | Что произойдёт |
|---|---|
| `/setbell OTHER I_IV 99 09:00-09:45` | звонок на 99-ю пару — мёртвая строка |
| `/setbell OTHER I_IV 0 09:00-09:45` | `para=0` — слот «Разговоров о важном», перезапишется |
| `/setbell OTHER I_IV 1 10:10-09:25` | пара кончается **раньше**, чем начинается |

Третье — худшее: `format_day` отрисует `10:10–09:25`, а `bell.py`
в `_tick` повесит «Конец пары» на 09:25, то есть **раньше** начала.
Напоминания поедут.

## Почему `para=0` опасен отдельно

`para=0` — не «нулевая пара», а слот «Разговоров о важном»:

```python
# common/schedule.py:225
rov = bell.get(("MONDAY", "ALL", 0))
# common/schedule.py:353
rov = bell.get((day_type, "ALL", 0))
```

Он рендерится отдельной строкой (`show_rov`), а не как пара. Перезапись
через `/setbell` сломает её молча.

## Что сделать

```python
if not 1 <= para <= 8:
    await message.answer("Номер пары — от 1 до 8.")
    return
if start >= end:
    await message.answer(
        f"Конец ({end:%H:%M}) должен быть позже начала ({start:%H:%M}).")
    return
```

Плюс `ALL` осмыслен только с `para=0` (для «Разговоров о важном»).
Если админ хочет именно его — пусть будет отдельная форма:

```python
if course_group == "ALL" and para != 0:
    await message.answer(
        "COURSE_GROUP=ALL бывает только у «Разговоров о важном» (para=0).\n"
        "Для пар используй I_IV или II_III.")
    return
```

Верхняя граница 8 — потому что у вуза 8 пар (`_format_bell_vuz`
перебирает `range(1, 9)`). Колледж использует 1–6.

## Что это не ломает

- Текущие 39 строк в `bell_schedule` все валидны: I_IV 1–6, VUZ 1–8,
  `ALL/0`. Проверка их не затронет.
- `/setbell` — единственный путь записи в `bell_schedule` из UI.
  `seed_if_empty` пишет напрямую и под проверку не попадает (данные
  корректны).

## Как проверить

```python
def test_setbell_rejects_inverted_times():
    """Пара не может кончаться раньше, чем начинаться."""

def test_setbell_rejects_out_of_range_para():
    """Номер пары — 1..8; para=0 зарезервирован под «Разговоры о важном»."""
```

Вживую: `/setbell OTHER I_IV 1 10:10-09:25` → должно отказать.

## Риски

- **`para=0` может понадобиться админу** для правки «Разговоров о
  важном» (сейчас это только `MONDAY/ALL/0`). Если да — разрешить
  `ALL` + `para=0`, но запретить `ALL` с другими номерами. Так и
  предложено выше.
- **Номера пар вуза и колледжа разные.** У вуза до 8, у колледжа до 6.
  Единая граница 8 не даст колледжу создать пару 7–8, которая никогда
  не отрисуется (`format_bell` перебирает `range(1, 6)` — план 023).
  После плана 023 граница должна стать общей.
