# План 113: админская рассылка игнорирует отписку

**Приоритет:** высокий. Это ровно та жалоба, с которой начался разбор
(«рассылка всем срёт этими уведомлениями»). Пользователь отписался,
но `/broadcast` ему всё равно пишет.

**Трудоёмкость:** S (~3 строки).

## Проблема

`_target_users` (`admin.py:480`) выбирает получателей тремя запросами,
и **ни один не смотрит на `subscribed`**:

```python
async def _target_users(repo: RequestsRepo, target: str):
    if target == "teachers":
        return await repo.users.get_teachers_users(), "преподавателям"
    if target == "all" or not target:
        return await repo.users.get_all(), "пользователям"
    return await repo.users.get_by_group(target), f"в группе {target}"
```

Все три репозиторных метода (`user.py:171-184`):

```python
async def get_all(self) -> list[User]:
    result = await self.session.execute(select(User))          # без фильтра
    return list(result.scalars().all())

async def get_by_group(self, group: Optional[str]) -> list[User]:
    cond = User.group.is_(None) if group is None else (User.group == group)
    result = await self.session.execute(select(User).where(cond))   # без subscribed
    return list(result.scalars().all())

async def get_teachers_users(self) -> list[User]:
    result = await self.session.execute(
        select(User).where(User.role == "teacher", User.teacher_name.is_not(None)))
    return list(result.scalars().all())                            # без subscribed
```

## Масштаб — проверил на проде

```
get_all()          -> 244 человека
get_subscribed()   -> 229
  из них отписались            -> 11
  без группы и без имени       ->  4
```

Точную цифру проверил запросом: `244 - 11 - 4 = 229`.

**Одиннадцать человек получат каждую админскую рассылку**, хотя нажали
«Отключить уведомления». Все — студенты:

```
id=1034370364  ЭК-25        id=1145868821  ЮРф-26
id=6524310606  ЮР-25Б       id=6462460007  СМ-26КП
id=1332680984  ТЭк-26       id=5994903750  ЭК-23
id=1353491487  ПР-26КП      id=6629888790  АП-25оз@vuz
id=1427627798  ТЭф-24
id=2113728780  ЮР-25А
id=5671952556  ЭОф-24
```

**Важно:** это не про расписание. Автоматические уведомления о
расписании (`poller.py`) фильтруют по `subscribed` правильно — там
`get_subscribed()`. Дыра только в ручных админских командах.

Но человек этого не различает: он отписался от уведомлений, а они
продолжают приходить. Именно так и рождается жалоба.

## Что сделать

Три строки — заменить источники на подписанные:

```python
async def _target_users(repo: RequestsRepo, target: str):
    if target == "teachers":
        return await repo.users.get_subscribed_teachers(), "преподавателям"
    if target == "all" or not target:
        return await repo.users.get_subscribed(), "пользователям"
    return await repo.users.get_subscribed_by_group(target), f"в группе {target}"
```

**Два метода уже есть:**
- `get_subscribed()` (`user.py:116`) — фильтрует `subscribed == True` и
  требует группу или имя преподавателя
- `get_subscribed_by_group()` (`user.py:135`) — то же плюс группа

**Третьего нет.** `get_teachers_users()` придётся дополнить или
добавить `get_subscribed_teachers()`. Проще — добавить условие в
существующий метод:

```python
async def get_teachers_users(self) -> list[User]:
    result = await self.session.execute(
        select(User).where(User.role == "teacher",
                           User.teacher_name.is_not(None),
                           User.subscribed == True))   # noqa: E712
    return list(result.scalars().all())
```

Проверил: сейчас у `get_teachers_users()` 2 человека, оба подписаны —
поведение не изменится, но станет правильным.

## Проверено и признано корректным

**Автоматические рассылки фильтруют правильно.** `notify_new_schedule`
(`poller.py`) берёт `repo.users.get_subscribed()`, а `get_subscribed`
требует `subscribed == True`. Плюс фильтр по группе (план 101, коммит
`74e6c5c`) отсекает чужие группы.

**`get_bell_subscribers` тоже корректен.** Требует `subscribed == True`
и `bell_mode != "off"`.

**`get_by_group("СМк-25")` даёт 27 человек, и все 27 подписаны** —
значит для этой группы правка ничего не изменит. Утечка только там,
где в группе есть отписавшиеся.

**`_confirm_broadcast` показывает число до отправки.** Админ видит
«Отправить 244 пользователям?» — после правки станет «233». Это и есть
честная цифра.

## Риски

- **Админ может хотеть написать всем, включая отписавшихся.** Например,
  объявление о сбое. Тогда нужен отдельный флаг «игнорировать
  отписку», а не снятие фильтра по умолчанию. Сейчас такого флага нет,
  и молчаливая отправка всем — не то поведение, которое стоит
  сохранять.
- **`get_subscribed()` отсекает не только отписавшихся.** В базе есть
  **четыре** подписанных пользователя без группы и без имени:

  ```
  id=6602662332  role=teacher  group=None  teacher_name=None
  id=6231955455  role=student  group=None  teacher_name=None
  id=6692409439  role=student  group=None  teacher_name=None
  id=7749685971  role=student  group=None  teacher_name=None
  ```

  Им нечего показать в расписании, поэтому для «всем» их отсечение
  правильно. Но цифра изменится на **15**, а не на 11 — админ это
  заметит и спросит. Стоит либо упомянуть в ответе бота, либо
  использовать `subscribed == True` без требования группы.
