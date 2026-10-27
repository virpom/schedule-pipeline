# План 006: преподаватель вуза должен видеть замены и не дублировать пары

> **СДЕЛАНО 27.10.2026** (коммит `b7ae1b9`).
>
> День идёт через `get_day_slots` по группам преподавателя (новый
> `get_teacher_groups`), с фильтром по своим парам и склейкой по
> нормализованному ключу `(para, para_end, subject, teacher)`; группы
> собираются в подпись пары. В `Slot` добавлено поле `date` — без него
> `format_week` не сгруппирует.
>
> Уточнение по проду на 27.10: вузовских преподавателей в боте **нет** —
> зарегистрированы 3, все колледжные (Данилова, Молчанова, Боровик; у
> всех по вузу 0 пар). Фидарова М.Г. есть в `base_lesson` (47 пар), но
> не в `users`. Дефект латентный, включается сразу, как
> зарегистрируется первый вузовский преподаватель.

**Приоритет:** шестой. Кривизна видна, но охват — 3 человека в вузе.

**Трудоёмкость:** M (правка в `user.py` + новый метод в репозитории).

## Проблема

`tgbot/handlers/user.py:331` `_vuz_teacher_day` читает **базовый слой
напрямую**, минуя `get_day_slots`:

```python
async def _vuz_teacher_day(repo, user, date):
    from tgbot.services import sync_vuz
    anchor = await sync_vuz.get_anchor(repo)
    week = sync_vuz.vuz_week(date, anchor)
    rows = await repo.base_lessons.get_for_teacher(
        user.teacher_name, weekday=date.isoweekday(), week=week)
    return [_vuz_lesson_to_slot(r) for r in rows]
```

Три следствия:

### 1. Замены вуза не видны

В базе **153 замены вуза** (`group LIKE '%@vuz'`). `get_for_teacher`
читает `base_lesson`, где замен нет — они в `substitution`. Студент вуза
видит их (читает `college_lesson`, где замены материализованы),
преподаватель — нет.

### 2. День и неделя показывают разное

`_user_lessons` (строка 357) складывает колледж + вуз:
```python
college = await repo.college_lessons.get_for_teacher_date(...)
vuz = await _vuz_teacher_day(...)
return sorted([*college, *vuz], key=lambda l: l.para)
```

А `_user_lessons_range` (строка 365) вуз **не включает вообще**:
```python
if _is_teacher(user):
    return await repo.college_lessons.get_for_teacher_range(...)
```

**Проверено на проде** (Фидарова М.Г., 27.10.2026):
- экран «Сегодня»: 18 пар,
- экран «Неделя»: 22 пары за ту же неделю.

**Перепроверка позже (26.10.2026):** числа изменились — база с тех пор
перематериализовалась. Сейчас для той же Фидаровой на 27.10:

```
college_lesson (студенческий путь):   8 пар
base_lesson вторник (путь препода):  14 строк
```

То есть дублей уже не 18 на 10, а **14 строк на 8 слотов** — всё ещё
почти вдвое больше, чем нужно.

Расхождение дня и недели стало абсолютным. Проверил её распределение:

```
колледж:  0 пар
вуз:     32 пары
         27.10 - 8, 28.10 - 6, 30.10 - 4,
         02.11 - 4, 03.11 - 6, 06.11 - 4
```

У неё **нет ни одной пары колледжа**. Значит «Неделя» покажет ей
пустоту за всю неделю, хотя в вузе у неё шесть дней с парами. Это не
расхождение на пару строк — это пустой экран вместо расписания.

Суть дефекта та же, конкретные числа в первом замере — нет.

### 3. Пары дублируются

`get_for_teacher` возвращает все строки по фамилии без дедупликации.
Один преподаватель ведёт 5 групп — на одну пару приходится 5 строк.
`format_day` с `merge_groups=True` склеивает по
`(para, subject, teacher)`, но **только если предмет совпадает точно**.
«Теория вероятностей (лек.)» и «Теория вероятностей (лек)» — разные
ключи, поэтому в списке две строки «4)» подряд.

Замер на проде для Фидаровой М.Г.: 18 строк, из них 10 уникальных
`(para, subject, group)`. Студент видит две пары с номером «4».

## Что сделать

### 1. Собирать пары вуза через `get_day_slots`

Вместо чтения `base_lesson` напрямую — пройти по группам вуза, где
преподаватель ведёт пары, и сложить результат:

```python
async def _vuz_teacher_day(repo, user, date):
    """Пары преподавателя вуза на дату — через итоговый слой.

    Раньше читали base_lesson напрямую: замены не применялись,
    и одна пара дублировалась по числу групп.
    """
    from tgbot.services.schedule_layer import get_day_slots
    groups = await repo.base_lessons.get_teacher_groups(
        user.teacher_name, weekday=date.isoweekday())
    slots = []
    for group in groups:
        slots.extend(await get_day_slots(repo, group, date))
    return slots
```

Нужен новый метод `get_teacher_groups` в `base_lesson.py` —
`SELECT DISTINCT group WHERE group LIKE '%@vuz' AND teacher LIKE '%surname%'`.

**Проверить:** `get_day_slots` для группы вуза сам разбирается с
`weeks` и чётностью (он уже это делает для студентов). Значит
дублирование исчезнет само.

### 2. Включить вуз в недельный экран

`_user_lessons_range` (строка 365):

```python
async def _user_lessons_range(repo, user, start, end):
    if _is_teacher(user):
        college = await repo.college_lessons.get_for_teacher_range(
            user.teacher_name, start, end)
        vuz = []
        day = start
        while day <= end:
            vuz.extend(await _vuz_teacher_day(repo, user, day))
            day += datetime.timedelta(days=1)
        return sorted([*college, *vuz], key=lambda l: (l.date, l.para))
    return await repo.college_lessons.get_for_group_range(user.group, start, end)
```

Проверить тип возврата: `get_for_teacher_range` возвращает объекты с
`.date`, `_vuz_teacher_day` — `Slot` без даты. Придётся либо добавить
дату в `Slot`, либо собирать список кортежей. Свериться с тем, как
`format_week` потребляет результат.

### 3. Нормализовать предметы при склейке

`common/schedule.py:170` `_merge_groups` — ключ по точному `subject`.
Добавить нормализацию вроде `teacher_base`, но для предметов:

```python
def subject_base(subject: str) -> str:
    """Ключ для склейки: «(лек.)» и «(лек)» — одно и то же."""
    return re.sub(r"[\s.]+", "", subject or "").lower()
```

Использовать **только как ключ склейки**, в тексте оставить исходный
вариант. Иначе «(прак. )» с пробелом и без склеятся, а показан будет
один из них — что и нужно.

### 4. Тест

В `tests/test_teacher_view.py` (он уже есть, 9 тестов):

```python
def test_vuz_teacher_sees_substitutions():
    """Замена вуза должна попадать в расписание преподавателя.

    Раньше _vuz_teacher_day читал base_lesson напрямую, и 153 замены
    вуза для преподавателей не существовали.
    """
```

## Как проверить

```bash
.venv/bin/python -m pytest tests/test_teacher_view.py -q
```

Вживую: взять преподавателя вуза, сравнить экран «Сегодня» и
«Неделя» — число пар за один день должно совпасть.

## Риски

- **Производительность.** `get_day_slots` на каждую группу — это
  N запросов вместо одного. У Фидаровой 5–7 групп; при 14 днях недели
  это ~100 запросов. Приемлемо, но если станет медленно — собрать
  батчем.
- **Преподаватель ведёт и колледж, и вуз.** Колледжеская часть уже
  приходит из `college_lesson`. Не задвоить: `get_day_slots` для
  `@vuz`-групп вернёт только вуз.
- **`Slot` без даты.** Для недельного экрана нужна дата — проверить,
  как её передаёт `format_week`, возможно, придётся добавить поле.
