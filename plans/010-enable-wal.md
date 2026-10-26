# План 010: включить WAL — иначе запись блокирует БД целиком

**Приоритет:** десятый. Дёшево, снимает класс проблем «database is locked».

**Трудоёмкость:** S (~10 строк + 1 тест).

## Проблема

`infrastructure/database/setup.py` — 7 строк, ни одной настройки SQLite:

```python
def create_engine(db: Db, echo: bool = False):
    return create_async_engine(db.sqlalchemy_url(), future=True, echo=echo)
```

Проверено на боевой БД:

```
journal_mode: ('delete',)
busy_timeout: (5000,)
synchronous: (2,)
```

`journal_mode=delete` означает: **любая запись блокирует базу целиком**.
Читатель ждёт писателя, писатель ждёт читателя.

## Почему это важно именно здесь

1. **`DatabaseMiddleware` пишет на каждое событие.** Любой тап по
   кнопке — это UPSERT в `users` + commit. При 227 пользователях это
   постоянный поток коротких записей.

2. **Пересборка держит запись 3.58 с** (план 008). Пока идёт
   `materialize`, другие записи ждут.

3. **`busy_timeout=5000`** — через 5 секунд ожидания приходит
   `sqlite3.OperationalError: database is locked`. Обработчик падает.

4. **Два старосты одновременно** — реалистичный сценарий (на проде 2
   редактора). Второй может получить отказ.

## Что сделать

### 1. Включить WAL при создании движка

`infrastructure/database/setup.py`:

```python
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from config import Db


def create_engine(db: Db, echo: bool = False):
    engine = create_async_engine(db.sqlalchemy_url(), future=True, echo=echo)

    @event.listens_for(engine.sync_engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=10000")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()

    return engine


def create_session_pool(engine):
    return async_sessionmaker(bind=engine, expire_on_commit=False)
```

`WAL` даёт: читатели не блокируют писателя, писатель не блокирует
читателей. `synchronous=NORMAL` безопасен в WAL и заметно быстрее
`FULL` (это `2`), особенно на 42 коммитах за пересборку.

### 2. Проверить, что не сломает бэкапы

WAL создаёт файлы `database.db-wal` и `database.db-shm` рядом с базой.
Проверить:

- **Docker volume** — `/home/virprom/schedule-pipeline/data` смонтирован
  целиком, файлы попадут туда же. Нормально.
- **Бэкап-скрипт** — если он копирует только `database.db`, копия будет
  неполной. Найти и проверить: `grep -rn "database.db" --include=*.sh .`
  или в cron на проде.

### 3. Проверить на копии

```python
# после правки
import sqlite3
c = sqlite3.connect('/tmp/copy.db')
print(c.execute('pragma journal_mode').fetchone())   # ('wal',)
```

## Как проверить

```bash
.venv/bin/python -m pytest -q          # все 183 должны пройти
```

На проде после деплоя:

```bash
docker exec <bot> python -c "
import sqlite3; c=sqlite3.connect('/data/database.db')
print('journal_mode:', c.execute('pragma journal_mode').fetchone())"
```

Ожидаемо `('wal',)`. Заметить: `-wal` и `-shm` появятся рядом.

## Риски

- **Сетевые ФС.** WAL не работает на NFS/SMB. Здесь локальный диск
  (Docker volume на VPS) — проверено, что `journal_mode` переключился.
- **Бэкап.** Главный риск: если бэкап копирует один файл, он потеряет
  свежие транзакции из `-wal`. Проверить перед включением на проде.
- **Не трогать `run_migrations_sync`** — он создаёт свой движок для
  alembic; pragma там не нужна, миграции идут разово при старте.
