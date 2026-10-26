# План 052: миграции могут примениться не к той базе

> **СДЕЛАНО 27.10.2026** (коммит `70e1b7b`).
>
> `env.py` уважает URL, переданный снаружи (`get_main_option` первым),
> и падает громко вместо молчаливого ухода в `database.db`. Runner
> передаёт соединение через `config.attributes`, так что `env.py` не
> поднимает второй движок и свой event loop.
>
> Проверено: 16 таблиц в указанной базе, версия `0007`, `college_lesson`
> с `id` и уникальным ключом, `bell_reminder` с `event_key`. Мусорного
> `database.db` больше не появляется — в том числе в проде.

**Приоритет:** средний. На проде не проявляется, но механизм держится
на случайном совпадении, а не на контракте.

**Трудоёмкость:** S (~10 строк).

## Как обнаружено

Написал тест: база, где есть только `users` (обрезанная старая база).
Ожидал падения `0001_baseline` на `table users already exists`.
Вместо этого:

```
INFO  [alembic.runtime.migration] Context impl SQLiteImpl.
INFO  [alembic.runtime.migration] Will assume non-transactional DDL.
ВЕРНУЛОСЬ БЕЗ ИСКЛЮЧЕНИЯ
таблицы: ['users']
```

Миграции **не применились вообще** — ни новых таблиц, ни
`alembic_version`. И **никакой ошибки**.

Проверил, куда они ушли:

```
ls -la database.db
-rw-r--r--  1 virprom  staff  200704 Oct 26 00:10 database.db
таблиц: 16
версия: [('0006_action',)]
```

В корне проекта появился `database.db` со **всеми 16 таблицами**. То
есть миграции применились, но **не к той базе**, которую я указал.

## Причина

`migrations_runner.py:44` ставит URL явно:

```python
def _alembic_config(config: Config) -> AlembicConfig:
    cfg = AlembicConfig(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "migrations"))
    cfg.set_main_option("sqlalchemy.url", _sync_url(config))   # <- ставит
    return cfg
```

Но при загрузке `migrations/env.py` **перезатирает** его безусловно:

```python
def _database_url() -> str:
    """Resolve DB URL: ALEMBIC_DB_URL wins, else SQLITE_PATH from .env."""
    explicit = os.getenv("ALEMBIC_DB_URL")
    if explicit:
        return explicit
    env_path = os.getenv("ENV_FILE", ".env")
    try:
        return load_config(env_path).db.sqlalchemy_url()
    except Exception:
        return "sqlite+aiosqlite:///database.db"    # <- молчаливый fallback

config.set_main_option("sqlalchemy.url", _database_url())   # строка 35
```

`set_main_option` от runner-а затирается при импорте `env.py`. Дальше
URL берётся из окружения — и если там пусто, падает в
`database.db` в текущей директории.

## Почему на проде работает

Проверил контейнер:

```
ls: cannot access '/app/.env': No such file or directory
SQLITE_PATH=/data/database.db
pwd -> /app
ls: cannot access '/app/database.db': No such file or directory
```

`--env-file` **не создаёт файл** внутри контейнера — он подставляет
переменные в окружение. Поэтому:

1. `env.py` пробует `open(".env")` → `FileNotFoundError` → `pass`;
2. `load_config` берёт `SQLITE_PATH` из `os.environ` → `/data/database.db`;
3. URL совпадает с тем, что поставил runner.

**Совпадает по случайности**: два независимых пути приходят к одному
результату. Если бы `SQLITE_PATH` не был задан — миграции ушли бы в
`/app/database.db`, а бот читал бы `/data/database.db` и падал на
отсутствии таблиц.

## Когда ломается

**Сценарий 1 — нет `SQLITE_PATH`.** Оператор запускает контейнер без
`--env-file` или с опечаткой в имени переменной. `load_config` берёт
дефолт `"database.db"`, `env.py` — тот же дефолт. Миграции проходят в
`/app/database.db`, приложение открывает `/data/database.db` (если путь
передан другим способом) — и не находит таблиц.

**Сценарий 2 — путь задан программно.** Любой скрипт или тест, который
строит `Config(db=Db(path="/tmp/x.db"))` и вызывает
`run_migrations_sync`, получит миграции **не в** `/tmp/x.db`. Ровно это
я и наблюдал.

**Сценарий 3 — `ALEMBIC_DB_URL` выставлен глобально.** Переменная
перебьёт всё, включая явно переданный `config.db.path`.

## Что сделать

`env.py` должен уважать URL, уже переданный снаружи, и падать, если
его нет:

```python
def _database_url() -> str:
    # URL мог поставить вызывающий код (migrations_runner) — он главнее.
    injected = config.get_main_option("sqlalchemy.url")
    if injected:
        return injected
    explicit = os.getenv("ALEMBIC_DB_URL")
    if explicit:
        return explicit
    env_path = os.getenv("ENV_FILE", ".env")
    try:
        return load_config(env_path).db.sqlalchemy_url()
    except Exception as e:
        raise RuntimeError(
            "Не удалось определить URL базы для миграций: задай "
            "ALEMBIC_DB_URL или SQLITE_PATH"
        ) from e
```

Два изменения:

1. **`config.get_main_option("sqlalchemy.url")` первым** — тогда
   `migrations_runner` действительно управляет тем, куда идут миграции.
2. **Убрать молчаливый fallback** — лучше громкая ошибка, чем
   миграции в чужой файл.

Проверил, что `alembic.ini:91` содержит `sqlalchemy.url =` (пусто),
так что `get_main_option` вернёт пустую строку при обычном
`alembic upgrade` из CLI — поведение CLI не изменится.

## Проверено и признано корректным

**`_stamp_baseline` работает правильно** — но только когда
`_looks_like_legacy_db` вернул `True`. Проверил: `all(has_table(t) for t
in ("users", "college_lesson"))`. Полная старая база (обе таблицы) —
помечается baseline, всё верно.

**Обрезанная база (только `users`) не распознаётся как legacy.**
`all()` требует **обе** таблицы. Если у кого-то есть база с одной
`users`, `_looks_like_legacy_db` вернёт `False`, runner скажет «пустая
БД — применяю все миграции», и `0001_baseline` упадёт на
`table users already exists`. **Но из-за дефекта URL это падение
случится в чужом файле**, а целевая база останется нетронутой — что
ещё хуже: ошибки не будет вовсе, а бот не стартует с непонятным
«no such table».

Стоит расширить проверку: legacy — если есть **любая** из маркеров, а
не все:

```python
def _looks_like_legacy_db(conn) -> bool:
    inspector = inspect(conn)
    return any(inspector.has_table(t) for t in _LEGACY_MARKERS)
```

**`run_migrations` уводит работу в поток** — `asyncio.to_thread`,
правильно: alembic синхронный.

**Временный движок закрывается** — `finally: engine.dispose()`.
Комментарий в докстроке объясняет зачем.

## Риски

- **`raise RuntimeError` вместо fallback** сломает сценарий «запустить
  `alembic upgrade` руками без `.env`». Но такой запуск и сейчас
  бесполезен — он создал бы пустую базу в текущей папке. Ошибка
  честнее.
- **Порядок проверки `config.get_main_option` первым** может помешать
  CLI, если в `alembic.ini` кто-то впишет URL статически. Проверил:
  строка пустая, так что сейчас безопасно.
- **`any` вместо `all` в legacy-детекте** может ошибочно пометить
  baseline базу, где случайно есть таблица `users` (например, чужая).
  Но `_LEGACY_MARKERS` — это имена именно наших таблиц, риск мал.
- **Мусорный `database.db` в корне** уже создан моими тестами и
  удалён. В `.gitignore` есть `*.db`, так что в коммит не попадёт, но
  стоит проверить, что его нет в рабочей копии.
