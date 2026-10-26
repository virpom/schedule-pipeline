# План 124: `env.py` перезаписывает URL, который ставит `migrations_runner`

**Приоритет:** низкий. Сейчас работает, но по совпадению, а не по
замыслу.

**Трудоёмкость:** S (~3 строки).

## Проблема

`run_migrations_sync` (`migrations_runner.py:74`) явно передаёт URL
в alembic:

```python
cfg = _alembic_config(config)
cfg.set_main_option("sqlalchemy.url", _sync_url(config))
command.upgrade(cfg, "head")
```

`_alembic_config` тоже ставит URL (`:44`):

```python
cfg.set_main_option("sqlalchemy.url", _sync_url(config))
```

Но `migrations/env.py:32` **перезаписывает его при импорте**, на
уровне модуля:

```python
config.set_main_option("sqlalchemy.url", _database_url())
```

где `_database_url()` (`:23`):

```python
def _database_url() -> str:
    explicit = os.getenv("ALEMBIC_DB_URL")
    if explicit:
        return explicit
    env_path = os.getenv("ENV_FILE", ".env")
    try:
        return load_config(env_path).db.sqlalchemy_url()
    except Exception:
        return "sqlite+aiosqlite:///database.db"
```

То есть переданный из приложения URL **не используется никогда**.
Итоговый путь определяет `env.py` — по переменным окружения
`ALEMBIC_DB_URL` / `ENV_FILE` / `SQLITE_PATH`.

## Почему сейчас работает

Проверил контейнер:

```
SQLITE_PATH=/data/database.db
ENV_FILE=       (пусто)
/app/.env       нет
/app/*.db       нет
```

`env.py` берёт `load_config(".env")` → `.env` нет → `FileNotFoundError`
в `_read_env` проглатывается → `os.environ.get("SQLITE_PATH")` →
`/data/database.db`. Тот же путь, что передал `migrations_runner`.
**Совпало.**

## Чем это опасно

**1. Расхождение при явном пути.** Если когда-нибудь понадобится
прогнать миграции на копии базы:

```python
run_migrations_sync(Config(db=Db(path="/tmp/copy.db"), ...))
```

миграции уйдут в `/data/database.db`, **потому что `env.py` смотрит
только на переменные окружения**. Приложение думает, что мигрировало
копию, а мигрировало боевую. Молча.

**2. Тихий фолбэк на `database.db`.** Последняя строка `_database_url`:

```python
except Exception:
    return "sqlite+aiosqlite:///database.db"
```

Если `load_config` упадёт (нет `BOT_TOKEN` — он обязательный,
`os.environ["BOT_TOKEN"]`), `env.py` молча возьмёт `database.db`
в текущей директории. `run_migrations_sync` при этом отработает без
ошибки и создаст **пустую базу в `/app`**. Проверил: сейчас `/app/*.db`
нет, то есть не срабатывало.

**3. Двойная установка URL.** Два `set_main_option` подряд — читателю
непонятно, какой победит. Побеждает `env.py`, потому что выполняется
позже.

## Что сделать

**Убрать перезапись в `env.py`**, если URL уже задан:

```python
if not config.get_main_option("sqlalchemy.url", None):
    config.set_main_option("sqlalchemy.url", _database_url())
```

Тогда `migrations_runner` управляет путём, а `alembic upgrade` из
командной строки (без приложения) продолжит работать через
`_database_url()`.

**И убрать тихий фолбэк** — пусть падает громко:

```python
def _database_url() -> str:
    explicit = os.getenv("ALEMBIC_DB_URL")
    if explicit:
        return explicit
    return load_config(os.getenv("ENV_FILE", ".env")).db.sqlalchemy_url()
```

Пустая база в `/app` хуже, чем понятная ошибка при старте.

## Проверено и признано корректным

**`migrations_runner` обрабатывает legacy-базу правильно.** Логика:

```python
current = _current_revision(conn)
if current is None and _looks_like_legacy_db(conn):
    _stamp_baseline(conn)          # база есть, alembic_version нет
elif current is None:
    logging.info("пустая БД — применяю все миграции")
```

Без `_stamp_baseline` миграция `0001_baseline` упала бы на
`CREATE TABLE users` — таблица уже есть. Проверка по маркерам
`("users", "college_lesson")` разумна: это две таблицы, которые есть
в любой версии базы.

**`run_migrations` уводит работу в поток** (`asyncio.to_thread`) —
правильно, alembic синхронный.

**Отдельный движок закрывается** в `finally: engine.dispose()` —
комментарий в шапке объясняет зачем: иначе alembic оставит соединение
занятым в основном пуле.

**`render_as_batch=True`** в обоих режимах — обязательно для SQLite,
иначе `ALTER TABLE` не работает.

**`injected connection`** (`env.py:76`) обрабатывается верно: если
соединение передано извне, свой event loop не поднимается.

## Мелкое, попутно

**`config.py:23` и `:27` — мёртвые функции:**

```python
def _int(name: str, default: int) -> int:
    return int(os.environ.get(name) or default)

def _float(name: str, default: float) -> float:
    return float(os.environ.get(name) or default)
```

Проверил: `grep -rn "_int(\|_float("` — **0 вызовов** вне самих
определений. Остались от подхода «настройки в env»; сейчас
`poll_interval`, `notify_rate`, `night_start` читаются из БД
(`repo.settings.get_all()`, `poller.py:251`). Удалить.

**`infrastructure/database/setup.py`** — 11 строк, две функции-обёртки
над SQLAlchemy. Не мёртвые (используются в `main.py`), но и не нужные:
`create_async_engine(db.sqlalchemy_url(), future=True, echo=echo)`
вызывается в одном месте. Оставить как есть — это вопрос вкуса, а не
дефект.

## Риски

- **Правка `env.py` затрагивает запуск миграций при старте.** Если
  ошибиться с условием, бот не поднимется. Проверять надо на копии
  базы, а не на боевой.
- **Удаление фолбэка сделает `alembic upgrade` из CLI зависимым от
  `.env`.** Это скорее плюс: сейчас CLI молча создаёт пустую базу,
  если `.env` не найден.
