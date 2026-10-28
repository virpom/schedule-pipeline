# План 166: пустая `alembic_version` на живой базе откатывает её на baseline

> **СДЕЛАНО 28.10.2026.** План верен по причине, но версия миграций устарела (0011, не 0006). Пустая alembic_version больше не считается legacy-базой: `_has_version_table` различает «таблицы нет» и «таблица пуста», второе — RuntimeError с подсказкой. Коммит cd1ed7b.

**Приоритет:** низкий по вероятности, высокий по последствию. Сейчас
не достижимо (в `alembic_version` лежит `0006_action`), но при
восстановлении базы из дампа контейнер уйдёт в вечный цикл падений.

**Трудоёмкость:** S (~4 строки).

## Что происходит

`migrations_runner.py:45-52` решает, что делать с базой:

```python
current = _current_revision(conn)
if current is None and _looks_like_legacy_db(conn):
    logging.info("alembic: существующая БД — помечаю как %s", BASELINE_REVISION)
    _stamp_baseline(conn)
elif current is None:
    logging.info("alembic: пустая БД — применяю все миграции")
```

`_current_revision` (`:42-47`) возвращает `None` в **двух** разных
случаях, не различая их:

```python
def _current_revision(conn) -> str | None:
    if not inspect(conn).has_table("alembic_version"):
        return None
    row = conn.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).first()
    return row[0] if row else None
```

1. Таблицы `alembic_version` **нет** — действительно база до alembic.
2. Таблица **есть, но пуста** — база с миграциями, у которой потеряли
   строку версии.

`_stamp_baseline` (`:60-67`) вызывается без проверки и делает:

```python
conn.execute(text("CREATE TABLE IF NOT EXISTS alembic_version ..."))
conn.execute(text("DELETE FROM alembic_version"))        # <- затирает
conn.execute(text("INSERT INTO alembic_version VALUES (:v)"),
             {"v": BASELINE_REVISION})                   # "0001_baseline"
conn.commit()
```

## Что случится

```
База на 0006, но alembic_version пуста
  -> _current_revision = None
  -> _looks_like_legacy_db = True   (users и college_lesson есть)
  -> _stamp_baseline: alembic_version = "0001_baseline"
  -> command.upgrade(cfg, "head")
  -> применяет 0002_editors, 0003_changed, 0004_vuz, 0005_weeks, 0006_action
     на уже существующей схеме
```

`0002_editors` начинается с `op.create_table("base_lesson", ...)`
(`migrations/versions/0002_editors.py:19`). Таблица уже есть →
`OperationalError: table base_lesson already exists`.

**Контейнер падает при старте.** `run_migrations` вызывается в `main()`
до всего остального, исключение не ловится, `restart=unless-stopped`
поднимает контейнер снова — и он падает на том же месте. Бот не
работает, пока кто-то руками не починит `alembic_version`.

## Как это может произойти

Самый реалистичный путь — **восстановление из дампа**:

```
sqlite3 database.db .dump > backup.sql
# ... позже ...
sqlite3 new.db < backup.sql
```

Если дамп снимали `--no-table alembic_version` или восстанавливали
схему через `create_all`, версия теряется, а таблицы остаются.

Остальные пути: ручной `DELETE FROM alembic_version` при отладке,
прерванный `downgrade`, копирование файла базы инструментом, который
пропустил служебную таблицу.

## Проверил на проде

```
alembic_version: 1 строка, значение '0006_action'
```

Ветка не срабатывает — `current` не `None`. Дефект спящий.

Воспроизвёл механику на временной базе (таблицы `users`,
`college_lesson`, `base_lesson`, пустая `alembic_version`):

```
current = None
_looks_like_legacy_db = True
-> _stamp_baseline сработает: True
```

## Что сделать

**Различать «таблицы нет» и «таблица пуста».** Только первое — признак
базы до alembic:

```python
def _has_version_table(conn) -> bool:
    return inspect(conn).has_table("alembic_version")


def run_migrations_sync(config: Config) -> None:
    engine = create_engine(_sync_url(config), future=True)
    try:
        with engine.connect() as conn:
            has_table = _has_version_table(conn)
            current = _current_revision(conn)
            if current is None and has_table:
                # Таблица версий есть, но пуста: база уже под alembic,
                # и подставлять baseline нельзя — миграции применятся
                # повторно на существующей схеме.
                raise RuntimeError(
                    "alembic_version пуста, но таблицы на месте. "
                    "Схема не совпадает с историей миграций — "
                    "проставь версию вручную: alembic stamp head"
                )
            if current is None and _looks_like_legacy_db(conn):
                logging.info("alembic: существующая БД — помечаю как %s", BASELINE_REVISION)
                _stamp_baseline(conn)
            elif current is None:
                logging.info("alembic: пустая БД — применяю все миграции")
    finally:
        engine.dispose()
    ...
```

**`raise` лучше молчаливого `stamp`.** Явная ошибка говорит, что
делать (`alembic stamp head`), и не портит базу. Цикл падений
контейнера всё равно будет, но в логах — причина, а не
`table base_lesson already exists` без контекста.

**`_stamp_baseline` можно ещё сузить** — убрать `DELETE`, он там
лишний: `_stamp_baseline` вызывается только когда `current is None`,
то есть удалять нечего. Оставить `INSERT` (с `DELETE` на случай, если
таблица непустая, но `_current_revision` вернул `None` — чего быть не
может).

## Проверено и признал корректным

**`_looks_like_legacy_db` требует обе таблицы** — `all()`, не `any()`.
Обрезанная база (только `users`) не распознаётся как legacy, и
`0001_baseline` упадёт на `table users already exists`. Это разобрано
в [плане 052](052-migrations-wrong-database.md:148-160), там же
предложено `any()`.

**`command.upgrade` при пустой базе работает.** Нет ни одной таблицы →
`_looks_like_legacy_db` = `False` → `0001_baseline` создаёт всё с нуля.

**Временный движок закрывается** — `finally: engine.dispose()`,
правильно.

**`run_migrations` уводит работу в поток** — alembic синхронный,
`asyncio.to_thread` обязателен.

**Прод в порядке** — `alembic_version = '0006_action'`, все 16 таблиц
на месте, `PRAGMA journal_mode = delete`, `busy_timeout = 5000`
(дефолт aiosqlite), `foreign_keys = 0` (в моделях нет ни одного
`ForeignKey` — корректно). За 12 часов работы **0** ошибок
`database is locked`.

## Риски

- **`raise` заблокирует старт.** Это и есть цель: лучше не стартовать,
  чем стартовать с переприменёнными миграциями. Но если кто-то
  сознательно чистил `alembic_version`, ему придётся выполнить
  `alembic stamp head` — в сообщении об ошибке это написано.
- **Тест:** нужен случай «таблицы есть, `alembic_version` пуста» —
  ожидать `RuntimeError`. Сейчас в `tests/` тестов на
  `migrations_runner` нет вообще.
