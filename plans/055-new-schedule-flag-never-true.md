# План 055: «🆕 Новое расписание» не показывается никогда

**Приоритет:** низкий. Текст сообщения, не данные. Но признак
«новое» бесполезен, а рассылка в чаты шлёт фото без спроса.

**Трудоёмкость:** S (~8 строк).

## Проблема 1: `is_new` всегда `False`

`poller.py:114` запоминает состояние **до** материализации:

```python
async with session_pool() as db:
    repo = RequestsRepo(db)
    had_lessons = await repo.college_lessons.count_lessons()   # ВСЕГО пар в базе
    try:
        await sync_eios.materialize(repo)
    except Exception:
        logging.exception("материализация не удалась")
```

И через двадцать строк (`poller.py:145`):

```python
for date in sorted(dates):
    changes.append((date, had_lessons == 0 and date == today))
```

`had_lessons` — это **общее число пар в `college_lesson`**, без привязки
к дате. Условие `had_lessons == 0` истинно только когда база пуста
целиком, то есть при самом первом запуске.

Проверил прод:

```
count_lessons: 3927
```

Значит `had_lessons == 0` **невозможно**, и `is_new` всегда `False`.

Дальше в `notify_new_schedule` (`poller.py:157`):

```python
prefix = "🆕 <b>Новое расписание</b>\n\n" if is_new else "🔄 <b>Расписание изменилось</b>\n\n"
```

Студент **никогда** не увидит «🆕 Новое расписание» — всегда
«🔄 Изменилось». Для первого дня семестра, когда расписание появляется
впервые, это неверно: студент получает «изменилось» про то, чего
раньше не было.

## Что должно было быть

Проверять наличие пар **для этой даты**, а не во всей таблице:

```python
async with session_pool() as db:
    repo = RequestsRepo(db)
    existing = set(await repo.college_lessons.get_dates_for_group(...))
```

Или проще — считать «новым» день, для которого в базе **не было
строк** перед материализацией:

```python
async with session_pool() as db:
    repo = RequestsRepo(db)
    before = await repo.college_lessons.get_dates_all()   # set дат
    ...
for date in sorted(dates):
    changes.append((date, date not in before))
```

Метод `get_dates_for_group` в репозитории уже есть. Нужен вариант без
группы, либо собрать `set` из `get_all_lessons` — но это дорого.
Дешевле добавить в `CollegeLessonRepo`:

```python
async def get_dates(self) -> set[datetime.date]:
    result = await self.session.execute(select(CollegeLesson.date).distinct())
    return {r[0] for r in result}
```

Один `SELECT DISTINCT date` — на 3927 строках мгновенно.

## Проблема 2: чат получает фото безусловно

`poller.py:184` — у пользователя:

```python
photo = photos.random_photo(photos_path, weekday) if (user.send_image and not is_teacher) else None
```

`poller.py:193` — у чата:

```python
photo = photos.random_photo(photos_path, weekday)
```

Без флага. У модели `Chat` нет поля `send_image`:

```python
class Chat(Base, TimestampMixin):
    __tablename__ = "chats"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    title: Mapped[str] = mapped_column(String(128), default="")
    group: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
```

То есть отключить картинки в чате нельзя вообще. Каждая рассылка в
чат — это сообщение с текстом и отдельное сообщение с фото.

Сейчас не проявляется: `chats` — **0 строк**, ни один чат не подключён.
Но `/setgroup` работает (`admin.py:395`), и первый же подключённый чат
получит эту схему.

## Проблема 3: чат всегда получает `brief`

`poller.py:189`:

```python
text = format_day(date, lessons, bell, lunches, "brief")
```

Захардкожено. У пользователя — `user.bell_detail`, у чата выбора нет.
Тоже не баг, а недоделка: чат не может попросить подробное расписание
со временем пар.

## Проверено и признано корректным

**`had_lessons` считается до материализации** — это правильно по
замыслу: нужно знать состояние **до** обновления, чтобы отличить
«появилось» от «изменилось». Ошибка только в гранулярности: вся таблица
вместо конкретной даты.

**`changes` не пустой при изменении вуза** — проверено:
`college_changed` и `vuz_changed` объединяются через `if not
college_changed and not vuz_changed: return changes`. Логика верная.

**Даты замен добавляются отдельно** — `dates |=
repo.substitutions.get_dates(today)`. Комментарий объясняет: листок
замен приходит на несколько дней вперёд, фиксированное окно «сегодня +
2» их теряло. Верно.

**N+1 по сессиям в `notify_new_schedule` — не проблема.** Написал
тест: 220 отдельных сессий против одной общей:

```
220 отдельных сессий: 0.065 с
одна сессия на 220:   0.033 с
```

Разница 32 мс на весь цикл. Пул соединений сглаживает накладные
расходы. Оптимизировать не нужно, хотя код и выглядит расточительно.

**`no_lessons.replace_date` — мёртвый код.** Проверил `grep`: метод не
вызывается ниоткуда. И хорошо, потому что он удаляет **все** группы за
дату:

```python
async def replace_date(self, date, rows):
    await self.session.execute(delete(NoLessons).where(NoLessons.date == date))
```

Если бы вызвали для одной группы — снёс бы заметки всех групп на эту
дату. Удалить метод вместе с планом 033.

## Риски

- **Добавление `get_dates` в репозиторий** — новый метод, надо покрыть
  тестом. Но он тривиальный: один `SELECT DISTINCT`.
- **Флаг `send_image` для чатов** — потребует миграции (`ALTER TABLE
  chats ADD COLUMN send_image BOOLEAN DEFAULT 0`). Сейчас чатов ноль,
  так что миграция безопасна, но всё равно нужна.
- **Правка `is_new` изменит тексты рассылок** — старое «🔄 Изменилось»
  сменится на «🆕 Новое» для новых дней. Это улучшение, но поведение
  меняется, и первый день семестра покажет другой заголовок.
- **Рассылки пока не отправляются** (по указанию владельца), так что
  все три проблемы сейчас не наблюдаемы. Чинить можно не спеша.
