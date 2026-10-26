# План 047: миграции не воспроизводят схему `college_lesson`

**Приоритет:** средний. На проде всё работает, потому что схема пришла
из старой базы. Но развернуть проект с нуля по миграциям — и получить
другую таблицу, чем в проде, — это мина под восстановление из бэкапа.

**Трудоёмкость:** S (~15 строк в новую миграцию).

## Как проверено

Прогнал миграции на пустую базу:

```bash
ALEMBIC_DB_URL="sqlite+aiosqlite:////tmp/fresh.db" .venv/bin/python -m alembic upgrade head
```

Все шесть прошли без ошибок. Дальше сравнил `pragma table_info`.

## Что получилось

**Чистая база:**

```sql
CREATE TABLE "college_lesson" (
    date DATE NOT NULL,
    "group" VARCHAR(32) NOT NULL,
    para INTEGER NOT NULL,
    para_end INTEGER NOT NULL,
    subject VARCHAR(256) NOT NULL,
    teacher VARCHAR(128) NOT NULL,
    room VARCHAR(64) NOT NULL,
    source_url VARCHAR(512) NOT NULL,
    source VARCHAR(8) DEFAULT 'site',
    changed BOOLEAN DEFAULT 0 NOT NULL,
    action VARCHAR(8) DEFAULT '' NOT NULL
)
```

**Прод:**

```sql
CREATE TABLE "college_lesson" (
    id INTEGER NOT NULL,
    ... те же колонки ...,
    PRIMARY KEY (id),
    CONSTRAINT uc_college_lesson UNIQUE (date, "group", para)
)
```

**Модель** (`models/college_lesson.py`) требует и то и другое:

```python
__table_args__ = (UniqueConstraint("date", "group", "para", name="uc_college_lesson"),)
id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
```

То есть чистая база расходится **и с моделью, и с продом** по двум
пунктам: нет `id` и нет уникального ключа.

Комментарий в модели прямо говорит, что индекс должен быть:

```python
# В боевой БД этот индекс есть (создан до перехода на слои). Держим его
# и в модели: иначе тесты на in-memory SQLite не воспроизводят главное
# ограничение — одну пару на (дата, группа, номер).
```

Модель держит, а миграции — нет.

## Что реально ломается

**Проверил вставку на чистой базе** — `INSERT` проходит, дубликат
**создаётся**:

```
ВТОРАЯ ВСТАВКА: ok -> ДУБЛИКАТ создан!
строк в college_lesson: 2
```

То есть ограничения нет физически.

**Но активного бага нет** — код защищён с двух сторон:

1. `replace_date` сначала `DELETE` по дате, потом вставка — повторный
   вызов не плодит строки.
2. `_merge_para_clash` (`sync_eios.py:315`) схлопывает слоты с
   одинаковым `para` в один через « / », так что `materialize_day` не
   может передать два слота с одним номером.

Плюс `get_day_slots` собирает `sub_by_para` словарём — по одному
слоту на `para`.

Значит дефект **латентный**: любой новый код, который вставит дважды
(импорт из файла, ручная правка в обход `replace_date`, будущий
парсер), создаст дубликат — и студент увидит пару дважды, потому что
`get_for_group_date` читает всё без `DISTINCT`.

## Что НЕ работает — проверено на копии прода

Скопировал боевую базу и прогнал на ней миграцию. Первые две попытки
провалились, и обе — по делу.

**Попытка 1 — `add_column(primary_key=True)`:**

```python
with op.batch_alter_table("college_lesson", recreate="always") as batch:
    batch.add_column(sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True))
    batch.create_unique_constraint("uc_college_lesson", ["date", "group", "para"])
```

```
2. УПАЛО: CircularDependencyError
Circular dependency detected. ('changed', 'id', 'room', 'group', ...)
```

Alembic не может упорядочить копирование, когда меняется первичный
ключ.

**Попытка 2 — `add_column` без `primary_key`:**

```python
batch.add_column(sa.Column("id", sa.Integer(), nullable=True))
```

Миграция проходит, но колонка создаётся **без PK и без
AUTOINCREMENT**:

```sql
id INTEGER,        -- не INTEGER PRIMARY KEY AUTOINCREMENT
```

Последствия катастрофические. Вставка без `id`:

```
вставка без id: ok
строки: [(None, 'Тест')]        <- id = NULL
```

А ORM на такой строке падает при чтении:

```
прочитано 3 строк
AttributeError: 'NoneType' object has no attribute 'id'
```

SQLAlchemy использует `id` как identity key. `NULL` → `None` в
результате → `select` возвращает `None` вместо объекта. **Всё чтение
`college_lesson` сломается**, а это основной путь расписания.

## Что работает — ручное пересоздание

SQLite не умеет `ADD COLUMN ... PRIMARY KEY AUTOINCREMENT`. Нужно
пересоздать таблицу целиком:

```python
def upgrade() -> None:
    conn = op.get_bind()
    cols = {c["name"] for c in sa.inspect(conn).get_columns("college_lesson")}
    ucs = {u["name"] for u in sa.inspect(conn).get_unique_constraints("college_lesson")}

    # На проде id и uc_college_lesson уже есть — миграция должна быть
    # идемпотентной, иначе duplicate column name: id.
    if "id" in cols and "uc_college_lesson" in ucs:
        return

    op.execute("""
        CREATE TABLE college_lesson_new (
            id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
            date DATE NOT NULL,
            "group" VARCHAR(32) NOT NULL,
            para INTEGER NOT NULL,
            para_end INTEGER NOT NULL,
            subject VARCHAR(256) NOT NULL,
            teacher VARCHAR(128) NOT NULL,
            room VARCHAR(64) NOT NULL,
            source_url VARCHAR(512) NOT NULL,
            source VARCHAR(8) DEFAULT 'site',
            changed BOOLEAN DEFAULT 0 NOT NULL,
            action VARCHAR(8) DEFAULT '' NOT NULL,
            CONSTRAINT uc_college_lesson UNIQUE (date, "group", para)
        )
    """)
    op.execute("""
        INSERT INTO college_lesson_new
            (date, "group", para, para_end, subject, teacher, room,
             source_url, source, changed, action)
        SELECT date, "group", para, para_end, subject, teacher, room,
               source_url, source, changed, action
          FROM college_lesson
    """)
    op.execute("DROP TABLE college_lesson")
    op.execute("ALTER TABLE college_lesson_new RENAME TO college_lesson")
    op.execute("CREATE INDEX ix_college_lesson_date ON college_lesson (date)")
    op.execute('CREATE INDEX ix_college_lesson_group ON college_lesson ("group")')
    op.execute("CREATE INDEX ix_college_lesson_teacher ON college_lesson (teacher)")
```

**Проверено на копии прода и на пустой базе:**

```
до:    ['date','group',...,'action','id']
после: ['id','date','group',...,'action']     <- id в начале, PK, AUTOINCREMENT
строки: [(1, 'Старая')]
после 2-й вставки: [(1, 'Старая'), (2, 'Новая')]   <- автоинкремент работает

ORM прочитал 2 строк
  id=1 2026-10-26 Старая
  id=2 2026-10-27 Новая
```

**Идемпотентность проверена на проде:**

```
1. пропущено: колонка уже event_key
2. need_id=False need_uc=False
2. пропущено: всё уже есть
=== ПОСЛЕ ===
  college_lesson: 3927 строк, [..., 'id']
  bell_reminder: 176 строк, [..., 'event_key']
```

То есть на боевой базе миграция ничего не делает и данные не трогает,
а на новой — создаёт правильную схему.

## Проверено и признано корректным

**Все шесть миграций применяются на пустую базу без ошибок.** Порядок
`0001 → 0006` соблюдён, `alembic_version` встаёт на `0006_action`.

**`bulk_insert` не использует `on_conflict`** — простой
`insert(CollegeLesson).values(lessons)`. Поэтому отсутствие UNIQUE на
чистой базе не роняет вставку, а просто позволяет дубликат.

**`changed` и `action` добавляются миграциями** — `0003_changed` и
`0006_action` через `batch_alter_table`. То есть эти две колонки
синхронны, расхождение только по `id` и UNIQUE.

**`subject` расширяется до 256 в `0004_vuz`** — и в чистой базе, и на
проде `VARCHAR(256)`. Совпадает.

## Побочная находка: `bell_notify` — мёртвая колонка

В `users` на проде есть `bell_notify INTEGER DEFAULT 0`, которой **нет
в модели**. Миграция `0001_baseline` сама её называет «устаревшее»:

```python
"""baseline: схема до внедрения alembic (как в боевой БД)
Отражает реальную схему продовой SQLite: college_lesson БЕЗ id,
users с bell_notify (устаревшее) и т.д.
"""
```

Данные рассинхронизированы с `bell_mode`:

```
bell_notify=0  bell_mode=full       x2
bell_notify=0  bell_mode=off      x210
bell_notify=0  bell_mode=start_end  x7
bell_notify=1  bell_mode=full       x5
bell_notify=1  bell_mode=off        x2   <- включено, но звонки выключены
bell_notify=1  bell_mode=start_end  x1
```

Два человека с `bell_notify=1, bell_mode=off` — колонка врёт, но её
никто не читает, так что вреда нет. Удалять отдельной миграцией или
оставить как исторический след — на усмотрение владельца.

## Проверено практически

Собрал обе правки (047 + 048) в одну миграцию и прогнал на чистой базе:

```
1. bell_reminder: ok
2. college_lesson: ok
  bell_reminder:  ['id', 'user_id', 'date', 'event_key']
  college_lesson: [..., 'action', 'id']
```

После этого проверил поведение через репозитории:

```
1-я вставка: ok
2-я вставка ЗАБЛОКИРОВАНА: IntegrityError     <- уникальный ключ работает
is_sent -> False
mark_sent -> ok
повтор is_sent -> True                          <- звонки работают
```

То есть обе находки закрываются одной миграцией `0007`.

**Важно:** `id` встаёт **в конец** таблицы, а не в начало. Для ORM
неважно (доступ по имени), но `SELECT *` с позиционным разбором
сломался бы. Проверил — позиционного разбора в коде нет.

## Риски

- **`batch_alter_table(recreate="always")` копирует всю таблицу.** На
  проде 3927 строк — секунды. Но при запуске миграции бот должен быть
  остановлен, иначе вставки во время копирования потеряются.
- **Уникальный ключ падает, если в таблице уже есть дубликаты.**
  Проверил это на своей тестовой базе: после двух вставок одной пары
  миграция упала с `IntegrityError: UNIQUE constraint failed`. На
  проде дубликатов 0 (проверил), но на чужой базе — проверять заранее:

  ```sql
  SELECT date, "group", para, COUNT(*) FROM college_lesson
  GROUP BY 1,2,3 HAVING COUNT(*) > 1;
  ```
- **Порядок колонок изменится**: `id` встанет в конец, а не в начало.
  Для ORM это неважно (доступ по имени), но `SELECT *` с позиционным
  разбором сломается. Проверил — позиционного разбора в коде нет.
- **Уникальный ключ может не создатьс**я, если на проде уже есть
  дубликаты. Проверил: `college_lesson` на проде 3927 строк, ключ
  `uc_college_lesson` существует — значит дублей нет. Но на чужой базе
  стоит проверить перед миграцией:

  ```sql
  SELECT date, "group", para, COUNT(*) FROM college_lesson
  GROUP BY 1,2,3 HAVING COUNT(*) > 1;
  ```
