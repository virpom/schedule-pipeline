# План 015: логи не видны — `fileConfig` сбрасывает настройку

**Приоритет:** высокий для диагностики. Без логов чинить что-либо
почти невозможно.

**Трудоёмкость:** S (2 строки в `main.py` + 1 в `Dockerfile`).

## Проблема

`Dockerfile` — 9 строк, `PYTHONUNBUFFERED` не задан:

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt
COPY . .
CMD ["python", "main.py"]
```

> **Поправка.** Сначала я объяснил потерю логов буферизацией
> `PYTHONUNBUFFERED`. Проверил на живом проде — **причина другая**.
> Настоящая: `migrations/env.py:18` вызывает `fileConfig()`, который
> сбрасывает настройку из `basicConfig`. Подробности ниже.
> `PYTHONUNBUFFERED` всё равно стоит добавить, но он не главное.

**Проверено на проде:** контейнер работает 4 часа, `RestartCount=0`,
а `docker logs` содержит **3 строки** — только вывод миграции:

```
INFO  [alembic.runtime.migration] Context impl SQLiteImpl.
INFO  [alembic.runtime.migration] Will assume non-transactional DDL.
INFO  [alembic.runtime.migration] Running upgrade 0005_weeks -> 0006_action
```

При этом синхронизация работает: `last_sync_ok` = `2026-10-25T22:57:35`,
в `bell_reminder` 176 записей. Значит код исполняется — но
**логи не доходят до `docker logs`**.

Проверено: `docker exec ... sh -c 'echo PYTHONUNBUFFERED=$PYTHONUNBUFFERED'`
возвращает пустую строку.

## Настоящая причина: `fileConfig()` сбрасывает `basicConfig`

Проверил экспериментально. `migrations/env.py:18`:

```python
from logging.config import fileConfig
...
if config.config_file_name is not None:
    fileConfig(config.config_file_name)
```

`fileConfig` по умолчанию `disable_existing_loggers=True` и
**перенастраивает root logger** по `alembic.ini`:

```ini
[logger_root]
level = WARNING
handlers = console
```

Прогнал на своей машине:

```python
logging.basicConfig(level=logging.INFO)
print("root level до:", logging.getLogger().level)      # 20 (INFO)
logging.config.fileConfig("alembic.ini")
print("root level после:", logging.getLogger().level)   # 30 (WARNING)
```

Вывод:

```
root level до: 20 handlers: 1
root level после: 30 handlers: 1
```

То есть после миграций root logger переключён на **WARNING**, и все
`logging.info(...)` в коде перестают печататься. Проверил на проде:

- контейнер работает **4 часа**, `RestartCount=0`;
- `docker logs` — **3 строки**, только alembic;
- `poller started` и `bell loop started` (обе — `logging.info`)
  **отсутствуют**;
- при этом бот жив: 176 записей в `bell_reminder`, `last_sync_ok` =
  `2026-10-25T22:57:35`.

Почему alembic виден: у него свой логгер `[logger_alembic] level =
INFO` со своим handler — он не пострадал.

**Что видно, а что нет.** Root на WARNING, поэтому:

| Уровень | Видно | Что это |
|---|---|---|
| `ERROR` | да | `logging.exception(...)` — падения |
| `WARNING` | да | предупреждения |
| `INFO` | **нет** | вся штатная работа |

То есть **аварии видны, работа — нет**. Проверил конкретно:

- находка 9 (`logging.exception("не удалось пересобрать")`) — видна;
- находка 17 (`logging.exception("синхронизация вуза не удалась")`) —
  видна;
- `poller started`, `bell loop started`, `Target [ID]: success`,
  `notify_group_about_edit: ... -> N/M`,
  `snapshot_past_days: сохранено N дней` — **не видны**.

Для диагностики это хуже, чем кажется: нельзя понять, работает ли
поллер вообще, пока он не упадёт.

## Почему это критично

Сейчас нет способа увидеть:
- когда последний раз обновлялось расписание,
- были ли ошибки парсинга,
- что писал `_rebuild` при падении (план 009),
- приходили ли тревоги (план 016).

`docs/TROUBLESHOOTING.md` целиком построен на чтении логов
(`docker compose logs -f --tail=100 bot`) — и он не работает по двум
причинам сразу (см. план 014).

## Что сделать

### 1. Починить главное — `env.py`

Не давать `fileConfig` трогать root logger:

```python
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)
```

Но этого мало: `[logger_root] level = WARNING` всё равно понизит
уровень. Надёжнее — выставить уровень после миграций, в `main.py`:

```python
await run_migrations(engine, config)
setup_logging()          # повторно, после миграций
```

Или в `alembic.ini` поставить `[logger_root] level = INFO`. Первый
вариант безопаснее: он не зависит от того, что написано в конфиге
alembic.

### 2. Добавить в `Dockerfile`

```dockerfile
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
...
```

`PYTHONDONTWRITEBYTECODE=1` — заодно убирает `__pycache__` внутри
контейнера (они и так в `.dockerignore`, но всё равно создаются).

### 2. Заодно убрать хардкод зеркала

```dockerfile
RUN pip install --no-cache-dir -r requirements.txt
```

Строка `-i https://mirrors.aliyun.com/pypi/simple/` — китайское зеркало.
На российском VPS оно может быть медленнее обычного PyPI или недоступно.
Если оно нужно — вынести в build-arg:

```dockerfile
ARG PIP_INDEX_URL=https://pypi.org/simple
RUN pip install --no-cache-dir --index-url "$PIP_INDEX_URL" -r requirements.txt
```

Проверить перед сменой: работает ли `pypi.org` с прод-сервера.

## Как проверить

После деплоя:

```bash
docker logs --tail 20 bot-wi188f7kradbxpz2efrl7vms
```

Ожидаемо: видны `poller started`, `bell loop started`, строки
`базовое расписание обновлено: N пар` и `materialize` каждые 5 минут.

## Риски

- **Объём логов.** Ротация уже настроена: `json-file`, `max-size=10m`,
  `max-file=3` (проверено в `docker inspect`). 30 МБ максимум, ничего
  добавлять не нужно.
- **Зеркало PyPI.** Если сменить на `pypi.org`, сборка может стать
  медленнее (или быстрее) — замерить перед сменой. Не критично для
  задачи, можно отложить.
