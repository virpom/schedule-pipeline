# План 019: проверять `TZ` при старте

> **СДЕЛАНО 27.10.2026** (коммит `70e1b7b`). Отметка стояла в
> `plans/README.md`, но не в файле плана.

**Приоритет:** низкий, но правка в три строки ловит молчаливый отказ.

**Трудоёмкость:** S (~5 строк).

## Проблема

`config.py` **не знает про `TZ`**:

```python
def load_config(path: str = ".env") -> Config:
    _read_env(path)
    return Config(
        tg_bot=TgBot(token=os.environ["BOT_TOKEN"], admin_ids=_ids("ADMINS")),
        db=Db(path=os.environ.get("SQLITE_PATH") or "database.db"),
        schedule_url=...,
        photos_path=os.environ.get("PHOTOS_PATH") or "/data/photos",
    )
```

При этом `TZ` есть в `.env.example:23` и задокументирован в
`docs/DEPLOYMENT.md`. Он работает — но только потому, что Docker
прокидывает его через `--env-file`, а Python читает `TZ` из окружения
при инициализации `datetime`.

**Проверено на проде:** `TZ=Asia/Krasnoyarsk`, сдвиг +7 верный.

## Что сломается без `TZ`

Всё время в коде — naive `datetime.datetime.now()`. При `TZ=UTC`
(по умолчанию в `python:3.11-slim`):

| Механизм | Сейчас (UTC+7) | Без TZ (UTC) |
|---|---|---|
| Ночное окно 23:00–07:00 | опрос стоит ночью | опрос стоит **06:00–14:00** местного, то есть днём |
| Напоминания о звонках | 08:40 = 08:40 | 08:40 = **15:40** |
| `deadline_hour=18` | дедлайн в 18:00 | дедлайн в **01:00** следующего дня |
| `STALE_AFTER` | 30 мин | не зависит (относительный) |
| Даты в `college_lesson` | локальные | сдвиг на 7 часов, но дата обычно та же |

Самое опасное: **опрос встанет днём и пойдёт ночью** — то есть студенты
будут видеть вчерашнее расписание весь учебный день.

## Почему это не поймается само

- `datetime.now()` не бросает исключений — просто возвращает не то.
- В логах время тоже будет UTC, но это заметно только при сравнении.
- `source_state.is_stale()` использует относительную разницу — не
  заметит.
- Тесты используют фиксированные даты — не заметят.

## Что сделать

### 1. Проверка в `load_config`

```python
def load_config(path: str = ".env") -> Config:
    _read_env(path)

    tz = os.environ.get("TZ")
    if not tz:
        logging.warning(
            "TZ не задан — время будет UTC. Ночное окно и напоминания "
            "о звонках сместятся. Добавь TZ=Asia/Krasnoyarsk в .env.")
    elif tz.upper() == "UTC":
        logging.warning("TZ=UTC — если это не намеренно, расписание "
                        "будет жить по UTC, а не по местному времени.")

    return Config(...)
```

Логировать, а не падать: бот должен запуститься даже с неверным TZ
(иначе одна опечатка в `.env` положит сервис).

### 2. Проверить, что реально применилось

Строже — сверить сдвиг:

```python
import datetime as _dt

local = _dt.datetime.now()
utc = _dt.datetime.utcnow()
offset = round((local - utc).total_seconds() / 3600)
if offset == 0 and tz and tz.upper() != "UTC":
    logging.error("TZ=%s задан, но смещение 0 — часовой пояс не применился", tz)
```

Это ловит случай, когда `TZ` записан в `.env`, но не дошёл до процесса
(например, `--env-file` не сработал).

### 3. Тест

```python
def test_config_warns_without_tz(caplog, monkeypatch):
    """Отсутствие TZ — предупреждение, а не тихий UTC."""
    monkeypatch.delenv("TZ", raising=False)
    monkeypatch.setenv("BOT_TOKEN", "x")
    load_config("/nonexistent")
    assert any("TZ не задан" in r.message for r in caplog.records)
```

## Как проверить

```bash
.venv/bin/python -m pytest tests/ -q
```

На проде после деплоя — в логах (после плана 015) не должно быть
предупреждения про TZ.

## Риски

- **Не уронить старт.** Проверка только логирует. Если хочется строже —
  падать только при явно неверном `TZ` (несуществующая зона), а не при
  отсутствующем.
- **`datetime.utcnow()` устарел** в Python 3.12 (DeprecationWarning).
  Для проверки сдвига использовать
  `datetime.datetime.now(datetime.UTC).replace(tzinfo=None)`.
