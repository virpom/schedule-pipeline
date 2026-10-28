# План 111: неделя преподавателя вуза пустая — источник не тот

> **СДЕЛАНО 28.10.2026.** `_user_lessons_range` проходит по дням
> и добавляет `_vuz_teacher_day`, затем `_drop_vuz_covered`
> убирает дубли с `college_lesson` (план 137).

**Приоритет:** низкий сегодня, высокий при первом же вузовском
преподавателе. Дефект латентный: код неверен, но жертв пока нет.

**Трудоёмкость:** S (~10 строк).

## Проблема

Преподаватель вуза видит **день** правильно и **неделю** — пустой.

`_user_lessons` (`user.py:357`), режим «день»:

```python
if _is_teacher(user):
    college = await repo.college_lessons.get_for_teacher_date(user.teacher_name, date)
    vuz = await _vuz_teacher_day(repo, user, date)     # <- вуз добавляется
    return sorted([*college, *vuz], key=lambda l: l.para)
```

`_user_lessons_range` (`user.py:365`), режим «неделя»:

```python
if _is_teacher(user):
    return await repo.college_lessons.get_for_teacher_range(
        user.teacher_name, start, end)                 # <- вуза нет
```

Вузовских пар в недельном виде нет вообще.

## Почему это не сломало ничего сегодня

Проверил прод: **всего 3 пользователя с `role='teacher'`**, у двоих
заполнен `teacher_name`:

```
id=1039429314  Молчанова Н.А.   вуз=0 пар,  колледж=13
id=1037099659  Боровик И.А.     вуз=0 пар,  колледж=24
```

Оба — колледжные преподаватели, вузовских пар у них нет. Третий
пользователь с ролью teacher имени не имеет вовсе.

При этом вузовских преподавателей в базе много:

```
Плотников С.С.     49 пар
Поварницын С.В.    48
Смирнова А.Т.      44
Багомедова У.М.    43
Самойлова Л.П.     37
...
```

Ни один из них ботом не пользуется. **Первый же зарегистрировавшийся
увидит пустую неделю** и решит, что расписания нет.

## Почему это не исправляется одной строкой

У вуза нет материализованного слоя на будущее — пары лежат в
`base_lesson` со списком недель (`base_lesson.weeks`) и номером дня
(`weekday`). Запрос «за неделю» должен для каждой даты вычислить
номер недели вуза и проверить, входит ли он в список.

`repo.base_lessons.get_for_teacher` (`base_lesson.py:123`) умеет
фильтровать по `weekday` и `week`, но **по одной дате за раз**:

```python
async def get_for_teacher(self, teacher_name: str, weekday: int | None = None,
                          week: int | None = None) -> list[BaseLesson]:
```

Значит на неделю нужно семь вызовов — или один запрос с `IN` по
парам `(weekday, week)`.

## Что сделать

Собрать неделю так же, как собирается день, но циклом:

```python
async def _vuz_teacher_week(repo: RequestsRepo, user: User,
                            start: datetime.date, end: datetime.date):
    """Пары преподавателя вуза за диапазон дат."""
    from tgbot.services import sync_vuz
    anchor = await sync_vuz.get_anchor(repo)
    out = []
    d = start
    while d <= end:
        week = sync_vuz.vuz_week(d, anchor)
        rows = await repo.base_lessons.get_for_teacher(
            user.teacher_name, weekday=d.isoweekday(), week=week)
        for r in rows:
            slot = _vuz_lesson_to_slot(r)
            slot.date = d          # нужен date: недельный вид группирует по дате
            out.append(slot)
        d += datetime.timedelta(days=1)
    return out
```

**Подвох:** `_vuz_lesson_to_slot` возвращает `Slot`, у которого нет
поля `date` (у него `__slots__`, см. `schedule_layer.py:20`). Недельный
вид (`user.py:728`) группирует по `l.date`. Значит либо добавить
`date` в `Slot`, либо вернуть `BaseLesson` и группировать по
`weekday`.

Второй путь чище: `_week_text` уже умеет работать с объектами, у
которых есть `para`, `subject`, `teacher`, `room` и дата.

## Проверено и признано корректным

**Студент вуза неделю видит правильно.** Проверил: вузовские группы
материализуются в `college_lesson` на 13 дат (24.10 — 07.11).
`get_for_group_range` читает именно `college_lesson`, значит у
студента всё на месте:

```
АП-26@vuz   19 пар на 7 датах
ИС-26@vuz   12 пар на 6 датах
ДП-26       18 пар на 5 датах
СМк-25      23 пары на 6 датах
```

**День преподавателя собирается верно.** `_user_lessons` складывает
`college_lesson` и `base_lesson` вуза, сортирует по номеру пары.
Проверил код — правильно.

**`_vuz_teacher_day` передаёт `week`.** Проверил: `week` вычисляется
из якоря и уходит в `get_for_teacher`. Без него вернулись бы пары всех
недель семестра.

## Риски

- **Семь запросов вместо одного.** На неделю — семь вызовов
  `get_for_teacher`, каждый с `LIKE` по фамилии. Для одного
  пользователя это ничто (замер `users` без индекса: 0.157 мс), но
  если преподавателей станет много, стоит один запрос с `IN`.
- **`Slot` без `date`.** Если добавлять `date` в `__slots__`, это
  заденет все места, где `Slot` создаётся (`schedule_layer.py`).
  Проверить все конструкторы перед правкой.
- **Сегодня жертв нет.** Правка не срочная, но и не косметическая:
  первый вузовский преподаватель упрётся в неё сразу.
