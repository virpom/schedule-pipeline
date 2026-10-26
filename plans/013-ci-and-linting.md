# План 013: CI и линтер

**Приоритет:** низкий по срочности, высокий по отдаче — ловит регрессии
до прода.

**Трудоёмкость:** S (~30 строк конфига).

## Проблема

- **Нет CI.** Ни `.github/workflows/`, ни аналога. Проверить 183 теста
  можно только руками.
- **Нет конфига линтера.** `pyflakes` даёт 5 замечаний, но его никто
  не запускает штатно.
- **Нет форматтера.** Код написан аккуратно, но единообразие держится
  дисциплиной.
- **`requirements-dev.txt` врёт.** Пишет `pytest~=8.3.0`, а в venv
  стоит **9.1.1**, `pytest-asyncio~=0.24.0` против **1.4.0**.
- **Нет фиксации версии Python.** Docker — `3.11-slim`, локально —
  `3.12.5`. Сейчас безопасно (нет 3.12-only синтаксиса), но это
  невидимый дрейф.
- **8 тестовых файлов** дублируют DB-харнесс, `conftest.py` нет.

## Что сделать

### 1. Обновить `requirements-dev.txt`

```
pytest~=9.1
pytest-asyncio~=1.4
pyflakes~=3.2
```

Проверить, что тесты проходят на этих версиях (они уже проходят).

### 2. Конфиг линтера

Минимальный вариант — `ruff.toml`, он покрывает pyflakes и многое
другое одним инструментом:

```toml
# ruff.toml
target-version = "py311"
line-length = 100

[lint]
select = ["F", "E", "W", "I"]
ignore = ["E501"]          # длина строк — не догма
```

Или, если не хочется нового инструмента — `.flake8`:

```ini
[flake8]
max-line-length = 100
extend-ignore = E203, W503
exclude = .venv,migrations/versions
```

`migrations/versions` исключить: alembic-файлы автогенерируемые,
их стиль не наш.

### 3. CI

`.github/workflows/test.yml`:

```yaml
name: test

on:
  push:
    branches: [master]
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"      # как в Dockerfile, не 3.12

      - name: Установить зависимости
        run: |
          pip install -r requirements.txt -r requirements-dev.txt

      - name: Линтер
        run: ruff check .

      - name: Тесты
        run: python -m pytest -q
```

Важно: **Python 3.11**, как в проде. Это ловит дрейф, которого сейчас
не видно.

### 4. `conftest.py` (заодно)

Вынести общий харнесс из 8 файлов:

```python
# tests/conftest.py
import asyncio
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from infrastructure.database.models import Base


@pytest_asyncio.fixture
async def pool():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()
```

`pytest.ini` уже ставит `asyncio_mode = auto`, так что фикстура
подхватится без правок в тестах.

## Как проверить

```bash
.venv/bin/python -m pytest -q                 # 183 passed
.venv/bin/python -m ruff check . 2>/dev/null  # или pyflakes
```

После пуша — вкладка Actions на GitHub: зелёная галочка.

## Риски

- **Новый инструмент.** `ruff` — ещё одна зависимость. Если хочется
  минимум, хватит `pyflakes` (он уже стоит) + CI без линтера.
- **Красный CI на первом запуске.** 5 замечаний pyflakes нужно
  исправить (план 012) или добавить в ignore. Лучше исправить.
- **GitHub Actions** — репозиторий на GitHub (`virpom/schedule-pipeline`),
  значит Actions доступны бесплатно для публичного репо.
