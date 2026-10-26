# План 048: на свежей базе напоминания о звонках не работают вообще

**Приоритет:** высокий. Это не латентный дефект, как расхождение в
`college_lesson` из плана 047, а активная поломка: на базе, поднятой
миграциями, **звонки не приходят никогда**.

**Трудоёмкость:** S (~10 строк).

## Проблема

Миграция `0001_baseline:103` создаёт колонку `key`:

```python
sa.create_table(
    "bell_reminder",
    ...
    sa.Column("key", sa.String(64), nullable=False),
    sa.UniqueConstraint("user_id", "date", "key", name="uc_bell_reminder"),
)
```

А модель (`models/bell_reminder.py`) ждёт `event_key`:

```python
__table_args__ = (
    UniqueConstraint('user_id', 'date', 'event_key', name='uc_bell_reminder'),
)
event_key: Mapped[str] = mapped_column(String(64))
```

**На проде колонка называется `event_key`** — проверил DDL:

```sql
CREATE TABLE bell_reminder (
    id INTEGER NOT NULL,
    user_id BIGINT NOT NULL,
    date DATE NOT NULL,
    event_key VARCHAR(64) NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uc_bell_reminder UNIQUE (user_id, date, event_key)
)
```

То есть миграция **не соответствует ни модели, ни проду**. Прод
получил правильную колонку когда-то раньше, а baseline её
зафиксировал неправильно.

## Проверено практически

Поднял базу миграциями и вызвал репозиторий:

```
is_sent УПАЛ: OperationalError: no such column: bell_reminder.event_key
mark_sent УПАЛ: OperationalError: table bell_reminder has no column named event_key
```

Обе операции падают. То есть **вся подсистема напоминаний о звонках
неработоспособна** на такой базе.

## Что видит пользователь

`bell.py:94`:

```python
async with session_pool() as db:
    repo = RequestsRepo(db)
    if await repo.reminders.is_sent(user.id, today, key):
        continue
    await repo.reminders.mark_sent(user.id, today, key)
await send_message(bot, user.id, text)
```

`is_sent` падает **до** `send_message` — значит сообщение не уходит.

`bell_loop` ловит исключение:

```python
while True:
    try:
        await _tick(bot, session_pool, datetime.datetime.now())
    except Exception:
        logging.exception("bell tick failed")
    await asyncio.sleep(30)
```

Поэтому бот не падает и в логах раз в 30 секунд появляется
`bell tick failed`. Но у всех, у кого `bell_mode` включён, **звонки
молчат**. На проде таких 14 человек.

Это худший вид отказа: снаружи всё выглядит живым, ошибка только в
логе, а функция не работает.

## Почему тесты не поймали

Тесты строят схему из моделей, а не из миграций:

```python
await conn.run_sync(Base.metadata.create_all)
```

Так делают **8 из 17** тестовых файлов. Значит:

- в тестах колонка называется `event_key` — как в модели, — и всё
  зелёное;
- в проде тоже `event_key` — и всё работает;
- **только база, поднятая миграциями, сломана**, и её не проверяет
  никто.

## Что сделать

Миграция `0007_schema_drift` (можно объединить с планом 047, они про
одно и то же — расхождение модели и миграций).

**Для `bell_reminder`:**

```python
def upgrade() -> None:
    conn = op.get_bind()
    cols = {c["name"] for c in sa.inspect(conn).get_columns("bell_reminder")}
    if "event_key" not in cols:
        with op.batch_alter_table("bell_reminder") as batch:
            batch.alter_column("key", new_column_name="event_key")
```

`batch_alter_table` умеет переименование в SQLite через пересоздание
таблицы. Уникальный индекс `uc_bell_reminder` переедет вместе с
колонкой — но имя ограничения останется прежним, что нормально.

**Для `college_lesson`** — см. план 047: `batch_alter_table` с
`add_column(primary_key=True)` падает с `CircularDependencyError`, а без
`primary_key` создаёт `id INTEGER` без автоинкремента, и ORM потом
возвращает `None` на каждой строке. Рабочий способ — ручное
пересоздание таблицы, рецепт в плане 047.

**Для `users.bell_notify`** — решить: удалить или оставить. Данные
рассинхронизированы с `bell_mode`, никто не читает.

## Что сделать, чтобы это не повторилось

Добавить тест, который поднимает схему **миграциями** и сверяет с
моделью:

```python
def test_migrations_match_models(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path}/mig.db"
    subprocess.run(["alembic", "upgrade", "head"], env={**os.environ, "ALEMBIC_DB_URL": url}, check=True)
    # сверить таблицы и колонки с Base.metadata
```

Такой тест поймал бы **оба** расхождения — и `bell_reminder`, и
`college_lesson`. Он медленный (секунды), поэтому можно пометить
`@pytest.mark.slow` и гонять в CI отдельно.

## Проверено и признано корректным

**Семантику ключа проверил отдельно — она верна.** Подозревал, что
`event_key` вида `s:1` / `e:1` / `lunch` не содержит времени, поэтому
сдвиг пары не даст второго звонка. Разобрал три сценария:

1. **Смена группы в течение дня.** Ключ не содержит группы — только
   `(user_id, date, event_key)`. Но время пары берётся из сетки звонков
   по курсу, а не по группе, так что «пара 1 в 14:00» не бывает.
   Ключ не ломается.
2. **Переключение `bell_mode` днём.** С `start_end` на `full`
   добавляются `h1:1`, `h2:1`, `lunch` — их ещё не отправляли, придут.
   `s:1`/`e:1` уже прошли, повторно не нужны. Обратное переключение
   тоже ничего лишнего не даёт.
3. **Сдвиг сетки звонков.** Единственный реальный случай:
   `replace_bells` (`sync_eios.py:276`) перезаписывает сетку, когда
   меняется digest файла. Если пара 1 переехала с 8:40 на 10:20,
   `s:1` уже отправлен в 8:40 — второго звонка не будет.

   Но это событие раз в семестр (digest меняется только при
   переиздании файла звонков), и происходит вне учебного дня. Ценой
   отдельного плана не считаю.

Проверил на проде: за 24.10 ключи — `s:1..3`, `e:1..3`, `h1:1`,
`h1:3`, `h2:1`, `h2:3`, `lunch`, `lunch_end`. Дублей `(user_id, date,
event_key)` — **0**, уникальный индекс держит.

**`bell_reminder` на проде растёт и читается нормально** — 176 строк,
`event_key` заполнен. То есть на проде всё работает, проблема только у
новых развёртываний.

**Уникальный индекс на проде правильный** — `UNIQUE (user_id, date,
event_key)`, совпадает с моделью.

**`on_conflict_do_nothing` в `mark_sent`** использует
`index_elements=["user_id", "date", "event_key"]` — на проде совпадает
с реальным индексом, работает.

**Остальные таблицы совпадают.** Сверил все 16 таблиц автоматически:
кроме трёх найденных (`bell_reminder`, `college_lesson`, `users`),
расхождений по колонкам нет. `alembic_version` есть только в
миграциях — так и должно быть.

## Ещё одно расхождение в той же таблице: длина

Миграция объявляет `sa.String(32)`, модель — `String(64)`:

```python
sa.Column("key", sa.String(32), nullable=False)      # 0001_baseline
event_key: Mapped[str] = mapped_column(String(64))   # модель
```

**Проверил, чем это грозит.** В SQLite `VARCHAR(N)` — это `TEXT`,
длина не проверяется:

```
вставил 200 символов в VARCHAR(32): ok
```

То есть на текущей базе разницы нет. **Но если БД когда-нибудь
переедет на PostgreSQL**, `VARCHAR(32)` станет настоящим ограничением.
Реальные ключи короткие — `s:1`, `h1:2`, `lunch`, `lunch_end`,
максимум **9 символов** (проверил прод: `max(length(event_key)) = 9`),
так что запас есть. Но расхождение стоит выровнять в той же миграции:

```python
batch.alter_column("key", new_column_name="event_key", type_=sa.String(64))
```

**Заодно переименование меняет тип на объявленный в модели** —
проверил, после `alter_column` колонка стала `VARCHAR(32)`, потому что
alembic взял тип из текущей схемы. Если передать `type_`, будет
`VARCHAR(64)`.

## Риски

- **Переименование колонки пересоздаёт таблицу.** На проде 176 строк —
  мгновенно. Но если когда-нибудь накопятся сотни тысяч (сейчас рост
  ~44 строки в день, ~11 000 в год), копирование займёт заметное время.
- **На проде колонка уже называется `event_key`** — проверено на копии:
  `KeyError 'key'`, если миграция не идемпотентна. Нужна проверка
  `if "key" in cols and "event_key" not in cols`. Идемпотентная версия
  проверена: на проде пишет «пропущено», на пустой базе переименовывает.
- **`alter_column(new_column_name=...)` — проверил, работает.**
  Alembic 1.20.0 на SQLite переименовывает без `recreate="always"`:

  ```
  ПЕРЕИМЕНОВАНИЕ: ok
  колонки: ['id', 'user_id', 'date', 'event_key']
  ```

  Уникальный индекс переехал вместе с колонкой:
  `CONSTRAINT uc_bell_reminder UNIQUE (user_id, date, event_key)`.
- **Тест на миграции замедлит прогон.** Сейчас 183 теста проходят за
  3.1 с; один тест с `alembic upgrade` добавит ~1 с. Приемлемо.
