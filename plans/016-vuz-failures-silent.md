# План 016: сбой вуза должен тревожить админа

> **СДЕЛАНО 27.10.2026** (коммит `a635647`).
>
> `_report_failure` теперь понимает и `VuzParseError`: в тексте
> тревоги появляется «файлы вуза не разбираются». Сообщение для
> колледжа не изменилось. Сетевые сбои вуза по-прежнему молчат — как и
> у колледжа: лежащий сайт сам поднимется.

**Приоритет:** средний. Сейчас сбой вуза виден только в логах, которые
буферизуются (план 015).

**Трудоёмкость:** S (~10 строк).

## Проблема

`tgbot/services/poller.py:84`:

```python
try:
    async with session_pool() as db:
        repo = RequestsRepo(db)
        vuz_result = await sync_vuz.sync_once(session, repo)
        ...
except Exception:
    logging.exception("синхронизация вуза не удалась")
```

Всё. Ни `alerts.alert`, ни `_report_failure`. Для сравнения — блок
колледжа ниже (строка 96) вызывает `_report_failure`.

`sync_vuz.sync_once` при `VuzParseError` делает `raise` (строка 349),
и этот `raise` уходит в `except Exception` — то есть **структура файла
вуза сломалась, а админ не узнает**.

Проверено: `alerts.` встречается в `poller.py` только в
`_report_failure` (строки 29 и 42), который для вуза не вызывается.

## Что смягчает (но не решает)

1. `source_state.mark_ok_vuz` не вызывается при сбое → через 30 минут
   `is_stale_vuz()` вернёт `True`.
2. `user.py:657` показывает студенту предупреждение «данные устарели».
3. `admin.py:166` в `/stats` пишет «⚠️ Синхронизация вуза не проходила».

То есть админ **увидит**, если сам зайдёт в `/stats`. Но не получит
уведомление, как при сбое колледжа.

## Что сделать

### 1. Переиспользовать `_report_failure`

Она уже различает «сайт лежит» (молчим) и «структура сломалась»
(тревога). Проблема: она проверяет `isinstance(error, eios.EiosParseError)`,
а вуз бросает `vuz.VuzParseError`.

Расширить:

```python
async def _report_failure(bot, session_pool, config, error, source="college"):
    from parsers import vuz
    parse_errors = (eios.EiosParseError, vuz.VuzParseError)
    ...
    if isinstance(error, parse_errors):
        await alerts.alert(bot, repo, config, f"structure_{source}", ...)
```

Ключ тревоги `structure_vuz` отдельный, чтобы сбои не глушили друг
друга (в `alerts.alert` ключ — это `kind`).

### 2. Вызвать в блоке вуза

```python
except Exception as e:
    logging.exception("синхронизация вуза не удалась")
    await _report_failure(bot, session_pool, config, e, source="vuz")
```

И при успехе — снимать тревогу:

```python
if not vuz_result.get("failed"):
    await source_state.mark_ok_vuz(repo)
    await alerts.clear(bot, repo, config, "structure_vuz", "Файл вуза снова разбирается.")
```

`alerts.clear` уже сам проверяет, была ли тревога (`if not await
repo.settings.get(key): return`), так что лишних сообщений не будет.

### 3. Проверить `anchor_off`

`poller.py:78` уже логирует `logging.error("якорь недель вуза не
сходится...")`. Это тоже повод для тревоги — расписание молча поедет
на неделю. Добавить:

```python
for form in vuz_result.get("anchor_off") or []:
    await alerts.alert(bot, repo, config, f"anchor_{form}",
                       f"Якорь недель вуза не сходится ({form}). "
                       f"Проверь /setvuzanchor — расписание может съехать на неделю.")
```

## Как проверить

Тест в `tests/test_poller_vuz.py` (он уже есть, 2 теста):

```python
def test_vuz_parse_error_alerts_admin():
    """Сломанный файл вуза должен тревожить админа.

    Раньше ошибка уходила только в logging.exception, а логи
    буферизуются — админ не узнавал о поломке.
    """
```

## Риски

- **Спам.** `alerts.alert` не повторяет одинаковый текст (хранит хеш
  в `setting`), так что одна тревога на одну проблему. Проверено
  кодом `alerts.py` и 7 тестами.
- **Разные ключи.** `structure` (колледж) и `structure_vuz` (вуз) —
  независимы, сбой одного не глушит другой.
