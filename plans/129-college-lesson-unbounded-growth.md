# План 129: `college_lesson` растёт вечно, `digest_by_date` грузит всю таблицу

> **СДЕЛАНО / УСТАРЕЛО 27.10.2026.**
>
> Пункт 1 (прошлое не удаляется) закрыт раньше: `_purge_past` в
> поллере. Замер: прошлых строк в `college_lesson` — 0.
>
> Риск из плана «чистка ломает Историю» снят в раунде 214:
> `_hist_page` читает `day_snapshot` запасным источником, а у
> преподавателя архив подключён отдельно.
>
> Пункт 2 (`digest_by_date` грузит всю таблицу) замерил заново:
> 71.8 мс через ORM на 2925 строках, дважды за проход раз в 5 минут —
> около 0.05% времени. Прогноз плана (850 мс к концу года) не
> сбывается: таблица теперь ограничена окном 14 дней, а не растёт
> вечно. Уникальный индекс `(date, group, para)` уже используется,
> сортировки в памяти нет. Оптимизировать нечего.

**Приоритет:** средний. Сейчас 2.1 МБ и 58 мс — терпимо. К концу
учебного года будет ~30 МБ и ~850 мс на вызов, дважды за проход.

**Трудоёмкость:** S (~15 строк).

## Две связанные проблемы

**1. Прошлые даты никогда не удаляются.** `replace_date`
(`college_lesson.py:41`) удаляет только ту дату, которую перезаписывает:

```python
async def replace_date(self, date, lessons) -> None:
    await self.session.execute(delete(CollegeLesson).where(CollegeLesson.date == date))
    await self.session.commit()
    await self.bulk_insert(lessons)
```

Материализация идёт вперёд на 14 дней (`MATERIALIZE_DAYS = 14`) и
перезаписывает **будущие** даты. Прошлые не трогает никто — `grep` по
`purge|cleanup|delete_old|vacuum` даёт **0 совпадений**.

Проверил на проде:

```
college_lesson:  879 прошлых  +  3048 будущих  =  3927
диапазон дат:    2026-10-02 .. 2026-11-07  (20 дат)
```

**22% таблицы — прошлое**, которое продолжит копиться.

**2. `digest_by_date` грузит всю таблицу в память.**

`college_lesson.py:99`:

```python
result = await self.session.execute(
    select(CollegeLesson).order_by(
        CollegeLesson.date, CollegeLesson.group, CollegeLesson.para)
)
buckets = {}
for row in result.scalars().all():      # <- вся таблица в RAM
    buckets.setdefault((row.date, row.group), []).append(...)
```

Нет `where`, нет агрегации в SQL. Каждая строка превращается в
Python-кортеж, потом всё хешируется.

Вызывается **дважды за проход поллера** (`poller.py:117` и `:122`):

```python
before = await repo.college_lessons.digest_by_date()
...
after = await repo.college_lessons.digest_by_date()
```

## Замеры и прогноз

Замерил на проде сейчас:

```
digest_by_date:        57.6 мс  (20 дат, 3927 строк)
get_for_group_date:     0.76 мс
get_dates_for_group:    1.27 мс
materialize:            5.91 с
```

Рост линейный по числу строк. Проход идёт каждые 5 минут — 288 раз
в сутки:

| Строк | мс/вызов | Секунд CPU в сутки |
|---|---|---|
| 3 927 (сейчас) | 58 | 33 |
| 10 000 | 147 | 85 |
| 20 000 | 293 | 169 |
| 58 000 (конец года) | 851 | **490** |

К концу учебного года: **8 минут CPU в сутки** только на то, чтобы
дважды за проход пересчитать отпечатки всей истории. Плюс 30 МБ в
SQLite, который читается целиком в память.

## Что сделать

**1. Чистить прошлое.** В `materialize` (`sync_eios.py:401`) после
записи окна удалять даты старше, скажем, 30 дней:

```python
async def purge_before(self, cutoff: datetime.date) -> int:
    result = await self.session.execute(
        delete(CollegeLesson).where(CollegeLesson.date < cutoff))
    await self.session.commit()
    return result.rowcount
```

Вызывать раз в сутки, не каждый проход. **Но осторожно:** план 120
показал, что `college_lesson` — единственный источник кнопки
«📜 История». Если чистить, история станет короче. Правильный порядок:
сначала научить «Историю» читать `day_snapshot` (план 120), потом
чистить.

**2. Считать отпечаток в SQL.** Вместо выгрузки всех строк:

```python
result = await self.session.execute(
    select(
        CollegeLesson.date,
        CollegeLesson.group,
        func.group_concat(
            CollegeLesson.para, "|",
            CollegeLesson.subject, "|",
            CollegeLesson.teacher, "|",
            CollegeLesson.room, "|",
            CollegeLesson.changed, "|",
            CollegeLesson.action,
        ).label("payload"),
    )
    .group_by(CollegeLesson.date, CollegeLesson.group)
)
```

`group_concat` в SQLite не гарантирует порядок, поэтому нужно либо
`order_by` внутри агрегата (SQLite поддерживает `group_concat(x, sep)`
без `ORDER BY` до 3.44), либо сортировать после. Проще — оставить
Python-хеширование, но грузить **только нужные колонки** и только
за окно дат:

```python
.window = datetime.date.today() - datetime.timedelta(days=1)
.where(CollegeLesson.date >= window)
```

Даже это даст выигрыш: сравнивать «до/после» имеет смысл только для
дат, которые материализация трогает (сегодня + 14 вперёд).

**3. Не считать дважды, если нечего сравнивать.** `poller.py:117`
делает `before` **до** проверки, изменились ли файлы. Если хеши
файлов те же, материализация всё равно нужна (окно сдвигается), но
сравнение отпечатков — нет.

## Что проверил и признал корректным

**Все запросы идут по индексам.** Проверил `EXPLAIN QUERY PLAN`:

```
college_lesson по группе+дате:  SEARCH USING sqlite_autoindex (date=? AND group=?)
college_lesson по teacher+дате: SEARCH USING ix_college_lesson_date (date=?)
base_lesson по группе:          SEARCH USING ix_base_lesson_group (group=?)
substitution по дате:           SEARCH USING ix_substitution_date (date=?)
```

Индексы на месте: `ix_college_lesson_date`, `ix_college_lesson_teacher`,
`ix_college_lesson_group`.

**`teacher LIKE '%Фамилия%'` не использует индекс по teacher** —
ведущий `%` это запрещает. Но запрос всё равно быстрый (1.5 мс),
потому что SQLite сначала отсекает по `date` через
`ix_college_lesson_date`. Строк на одну дату мало (~290), фильтр по
фамилии дешёвый. Это работает.

**Нет ошибок блокировки.** Проверил логи за всё время:
`database is locked` — **0**, `OperationalError` — **0**.
`journal_mode = delete`, не WAL, но при одном писателе (поллер) и
коротких транзакциях этого достаточно.

**Размер базы не проблема сам по себе.** 2.1 МБ, `page_size = 4096`,
`freelist = 3`. Даже 30 МБ для SQLite — ничто. Проблема не в месте,
а в том, что таблица читается целиком.

**Понедельник покрыт нормально — проверил, подозрение не подтвердилось.**
Пока разбирался, заметил, что у `ДП-26` ноль пар на 26.10 (понедельник),
и сначала решил, что это дефект. Проверил распределение по дням:

```
wd=1: 35 групп, 129 пар
wd=2: 34 групп, 127 пар
wd=3: 34 групп, 137 пар
wd=4: 36 групп, 138 пар
wd=5: 32 групп, 124 пар
wd=6: 14 групп,  49 пар
```

Из 37 групп колледжа 35 имеют пары в понедельник. У `ДП-26` в
`base_lesson` просто нет строк с `weekday=1` — её расписание начинается
со вторника. Это не дефект.

**`get_for_teacher_date` вернул 0 строк для Молчановой на 26.10** —
и это верно. Проверил: у неё 13 пар, но ни одной в понедельник 26.10,
только 27.10 и дальше.

## Риски

- **Чистка `college_lesson` ломает «Историю».** Пока план 120 не
  сделан, `_hist_page` (`user.py:765`) читает именно эту таблицу.
  Удалять прошлое можно только после переключения на архив.
- **`group_concat` в SQLite не гарантирует порядок** — хеш станет
  нестабильным между вызовами. Если переносить агрегацию в SQL, надо
  явно сортировать строки перед конкатенацией.
- **Ограничение окна в `digest_by_date` может пропустить изменение**
  в дате за пределами окна. Но материализация такие даты и не трогает,
  так что сравнивать их нечего.
