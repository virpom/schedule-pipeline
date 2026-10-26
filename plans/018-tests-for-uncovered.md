# План 018: тесты на непокрытые модули

**Приоритет:** средний. 183 теста есть, но три сервиса не покрыты вовсе.

**Трудоёмкость:** M (3 файла тестов).

## Что не покрыто

Проверено: `grep -rln "bell\|notify_edits\|broadcaster" tests/` → пусто.

| Модуль | Строк | Тестов | Что внутри |
|---|---|---|---|
| `tgbot/services/bell.py` | 107 | **0** | расчёт событий звонков, дедупликация, обед |
| `tgbot/services/notify_edits.py` | 85 | **0** | рассылка об изменениях, `snapshot_past_days` |
| `tgbot/services/broadcaster.py` | 110 | **0** | rate limiting, обработка 429, повторы |
| `tgbot/middlewares/database.py` | 39 | **0** | создание пользователя на каждое событие |

Все четыре — код, который работает в фоне и ошибается молча.

## Что важнее покрыть

### 1. `bell.py` — самый сложный

Логика нетривиальна: три режима (`BELL_START_END`, `BELL_FULL`,
выключен), склейка событий по ключу `s:{para}`/`h1:{p}`/`e:{p}`,
обед `inside` vs `after`, фолбэк на `I_IV`.

Что тестировать:

```python
def test_bell_events_for_one_lesson():
    """Одна пара даёт начало, перемену, конец — в правильном порядке."""

def test_bell_events_deduplicated_for_teacher():
    """Преподаватель с 5 группами не получает 5 одинаковых звонков.

    Ключ события s:{para} — второй и далее пропускаются по is_sent.
    """

def test_lunch_not_duplicated_with_break():
    """Обед inside не должен дублироваться как перемена."""
```

### 2. `notify_edits.py` — риск рассылки не тем

```python
def test_notify_excludes_author():
    """Автор правки не получает уведомление о своей же правке."""

def test_notify_only_subscribers_of_group():
    """Уведомление уходит только подписчикам правленой группы."""

def test_snapshot_skips_sunday():
    """Воскресенье не учебный день — не сохраняем."""
```

### 3. `broadcaster.py` — 429 и лимиты

```python
def test_broadcast_rate_limits():
    """Между сообщениями выдерживается пауза 1/rate."""

def test_broadcast_survives_retry_after():
    """429 не роняет рассылку и сообщение доходит (см. план 017)."""
```

### 4. `middlewares/database.py`

```python
def test_middleware_creates_user_once():
    """Повторное событие не создаёт второго пользователя."""

def test_middleware_injects_repo_and_user():
    """Хендлер получает repo, user, config, session_pool."""
```

## Как это делать

Харнесс уже есть — но скопирован в 8 файлах. Перед написанием новых
тестов вынести в `tests/conftest.py` (см. план 013, пункт 4).

Для `bell.py` и `notify_edits.py` нужен поддельный `Bot`. Минимальный:

```python
class FakeBot:
    def __init__(self):
        self.sent = []
    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text))
```

Проверить, что `broadcast_many` принимает его (тип `Bot` не проверяется
в рантайме).

## Как проверить

```bash
.venv/bin/python -m pytest tests/test_bell_service.py \
    tests/test_notify_edits.py tests/test_broadcaster.py -q
```

## Риски

- **Тесты на детали реализации.** `bell.py` возвращает список кортежей
  `(time, key, text)`. Тестировать поведение (какие события и в каком
  порядке), а не точный текст — иначе каждый косметический правка
  ломает тесты.
- **Время в тестах.** `bell.py` зависит от `datetime.now()` и
  `date.today()`. Использовать фиксированные даты, как это уже делают
  `test_schedule_logic.py` и `test_source_state.py`.
