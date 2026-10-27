# План 046: роль `teacher` ставится до выбора фамилии — пользователь застревает

> **СДЕЛАНО 27.10.2026** (коммит `0c0b64c`).
>
> Часть 1: `set_role` убран из `cb_role_teacher`; роль ставит
> `cb_teacher` вместе с фамилией (она и раньше там писалась — запись в
> `cb_role_teacher` была лишней).
>
> Часть 2 (SQL по пяти застрявшим) **не выполнялась**: на проде таких
> нет. Проверено 27.10 — единственный кандидат `mourvane` уже выбрал
> «Данилова А.Н.». Три пользователя без группы — новые, ещё не
> выбравшие, это нормальное состояние, а не застревание.
>
> Часть 3: защита от `None` в `get_dates_for_teacher` и
> `get_all_for_teacher`.

**Приоритет:** низкий. Один человек на проде, но состояние
непоправимое из UI — он не может выйти из него сам.

**Трудоёмкость:** S (~6 строк).

## Проблема

`user.py:441`:

```python
@user_router.callback_query(F.data == "role:teacher")
async def cb_role_teacher(cb: CallbackQuery, repo: RequestsRepo, user: User):
    await repo.users.set_role(user.id, "teacher")     # <- сразу в базу
    await cb.message.edit_text("👨‍🏫 Где ты преподаёшь?", reply_markup=TEACHER_UNIT_KB)
```

Роль записывается **до** того, как человек выбрал подразделение и
фамилию. Если он ушёл на этом шаге (закрыл чат, отвлёкся), в базе
остаётся `role='teacher'` с `teacher_name=NULL`.

**На проде такой уже есть:**

```
id=6602662332  'mourvane'  group=None  role=teacher  teacher_name=None  unit=college
```

Всего преподавателей трое, у двух фамилия заполнена.

## Что видит этот человек

`_has_identity` (`user.py:87`):

```python
def _has_identity(user: User) -> bool:
    return bool(user.teacher_name) if _is_teacher(user) else bool(user.group)
```

`bool(None)` → `False`. Значит:

1. **`/start`** уходит в ветку «Привет! Кто ты?» и снова показывает
   выбор роли — хотя роль уже `teacher`. Человек не понимает, почему
   его спрашивают второй раз.
2. **Любое действие** («Сегодня», «История», поиск) получает ответ
   «Сначала выбери группу или фамилию 🎯» — и выбрать фамилию из этого
   состояния негде.
3. **Рассылки не приходят**: в `notify_new_schedule` для
   `role="teacher"` берётся `user.teacher_name`, а он `None` —
   `get_for_teacher_date(None, date)` вернёт `[]`, и человек попадёт
   в «Занятий нет».
4. **В админ-статистике** он считается преподавателем
   (`_build_stats_unit` фильтрует `u.role != "teacher"` для студентов).

То есть человек застрял: роль преподавателя, но без фамилии, и
выбрать её заново можно только через `/start` — который показывает
выбор роли, а не подразделения.

## Второй, скрытый дефект

`college_lesson.py:165` и `:175` — два метода **без защиты от пустого
имени**, в отличие от двух соседних:

```python
async def get_for_teacher_date(self, teacher_name, date):
    if not (teacher_name or "").strip():     # ЕСТЬ
        return []

async def get_for_teacher_range(self, teacher_name, start, end):
    if not (teacher_name or "").strip():     # ЕСТЬ
        return []

async def get_dates_for_teacher(self, teacher_name):
    surname = teacher_name.split()[0] if teacher_name.split() else teacher_name   # НЕТ
    ...

async def get_all_for_teacher(self, teacher_name):
    surname = teacher_name.split()[0] if teacher_name.split() else teacher_name   # НЕТ
    ...
```

При `teacher_name=None` выражение `teacher_name.split()` падает с
`AttributeError: 'NoneType' object has no attribute 'split'`.

**Проверил: через UI это недостижимо** — оба вызывающих места
(`user.py:770` в `_hist_page`, `user.py:901` в `subject_answer`) стоят
за `_require_identity`, который отсекает `teacher_name=None`. Но защита
держится на вызывающем, а не на методе, — и первый же новый вызов
без проверки уронит обработчик.

При `teacher_name=""` падения нет: `"".split()` → `[]`, `surname=""`,
`LIKE '%%'` вытащит всю таблицу и отфильтрует в Python через
`teacher_matches`. Результат верный, но **полная выгрузка таблицы** на
каждый вызов.

## Что сделать

**Часть 1 — не писать роль до выбора.** Убрать `set_role` из
`cb_role_teacher` и перенести в место, где фамилия уже известна:

```python
@user_router.callback_query(F.data == "role:teacher")
async def cb_role_teacher(cb: CallbackQuery, user: User):
    await cb.message.edit_text("👨‍🏫 Где ты преподаёшь?", reply_markup=TEACHER_UNIT_KB)
    await cb.answer()
```

А в обработчике выбора фамилии (там, где пишется `set_teacher_name`)
добавить `set_role(user.id, "teacher")`.

**Часть 2 — починить пятерых застрявших.** Одноразово, SQL-ом:

```sql
UPDATE users SET role=NULL
 WHERE (role='teacher' AND (teacher_name IS NULL OR teacher_name=''))
    OR (role='student' AND ("group" IS NULL OR "group"=''));
```

**Часть 3 — выровнять защиту.** Добавить в два метода ту же проверку:

```python
async def get_dates_for_teacher(self, teacher_name: str) -> list[datetime.date]:
    if not (teacher_name or "").strip():
        return []
    surname = teacher_name.split()[0]
    ...
```

Это не чинит застревание, но убирает `AttributeError` из-под ног
будущих вызовов.

## Та же болезнь у студентов — и она массовее

`user.py:435` устроен идентично:

```python
@user_router.callback_query(F.data == "role:student")
async def cb_role_student(cb: CallbackQuery, repo: RequestsRepo, user: User):
    await repo.users.set_role(user.id, "student")     # <- сразу в базу
    await cb.message.edit_text("🎓 Где ты учишься?", reply_markup=_unit_kb())
```

**На проде 4 таких человека:**

```
6231955455  ',,vvrrr🗯'      role=student  group=None
6692409439  'No name'        role=student  group=None
1588628434  'TheyshaRarri'   role=student  group=None
7749685971  'Ural Phantom'   role=student  group=None
```

Плюс `mourvane` с `role=teacher` — итого **5 застрявших из 227**.

Я ошибся, когда в первом черновике написал, что у студента «это
восстанавливается одним нажатием». На деле `/start` для него
показывает «Кто ты?» → он жмёт «Студент» → `set_role` → «Где ты
учишься?» → и если он снова уйдёт, ничего не изменится. То есть
цикл повторяется, а `_has_identity` всё время `False`.

Значит часть 1 плана (не писать роль до выбора) чинит **оба** пути,
а часть 2 (UPDATE) должна покрыть пятерых:

```sql
UPDATE users SET role=NULL WHERE (role='teacher' AND (teacher_name IS NULL OR teacher_name=''))
   OR (role='student' AND ("group" IS NULL OR "group"=''));
```

`role=NULL` (а не `'student'`) — потому что роль действительно не
выбрана; тогда `/start` покажет выбор с чистого листа.

**FSM-состояние не перепутается между людьми.** `MemoryStorage`
хранит по `(chat_id, user_id)`, так что незавершённый выбор фамилии
одного человека не повлияет на другого.

**`_require_identity` защищает все входы в поиск.** Проверил `cb_hist`
(`:710`), `cb_find` (`:878`), `cb_find_group` — все начинаются с
проверки.

## Риски

- **Перенос `set_role` меняет момент записи.** Если человек выбрал
  «Преподаватель», но не дошёл до фамилии, в базе он останется
  `student` (или `None`) — то есть роль будет «не определена», а не
  «teacher без фамилии». Это лучше: `/start` покажет выбор роли, и он
  сможет пойти по любому пути.
- **Часть 2 меняет данные на проде** — 5 человек из 227. Если кто-то
  из них реальный студент, который просто не дошёл до выбора, ему
  придётся выбрать заново. Это и есть цель, но стоит предупредить
  владельца бота.
- **`role=NULL` вместо `'student'`** может удивить код, который ждёт
  строку. Проверил: `_is_teacher` сравнивает с `"teacher"`, `_has_identity`
  делает `bool(user.group)`, `_build_stats_unit` фильтрует
  `u.role != "teacher"`. Нигде `role` не разыменовывается как
  гарантированно заполненный. Но `User.role` в модели объявлен
  `Mapped[str]` без `Optional` — при чтении `None` попадёт в
  `Mapped[str]`, что SQLAlchemy переживёт (типы не проверяются), но
  статический анализатор будет ругаться.
- **Часть 3 (проверка) скрывает ошибку вызывающего.** Если кто-то
  передаст `None`, метод молча вернёт `[]` вместо падения — баг
  станет тише. Стоит логировать.
