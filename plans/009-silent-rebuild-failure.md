# План 009: тихий отказ — староста не должен видеть «Сохранено» при провале

> **СДЕЛАНО 27.10.2026** (коммит `3d7f632`).
>
> `_rebuild` возвращает bool, обработчик не пишет «Сохранено» при провале. Тест `tests/test_undo_rebuild.py`.

**Приоритет:** девятый. Бот врёт о результате — самый неприятный класс
багов для доверия.

**Трудоёмкость:** S (~15 строк).

## Проблема

`tgbot/handlers/editor.py:881` `_rebuild` глотает любое исключение:

```python
async def _rebuild(repo, date=None):
    from tgbot.services import sync_eios
    try:
        if date is None:
            await sync_eios.materialize(repo)
        else:
            await sync_eios.materialize_day(repo, date)
    except Exception:
        logging.exception("не удалось пересобрать college_lesson")
```

Обработчик продолжает и отвечает успехом:

```python
await _rebuild(repo)
notified = await notify_group_about_edit(...)
...
text = "✅ <b>Сохранено</b>" + ...
await cb.answer("Сохранено")
```

Если `materialize` упал (заблокирована БД, нарушен UNIQUE, кончилось
место), староста видит «✅ Сохранено», а студент — старое расписание.
Единственный след — строка в логе, который к тому же буферизуется
(план 015).

## Что сделать

### 1. Возвращать результат из `_rebuild`

```python
async def _rebuild(repo, date=None) -> bool:
    """Пересобрать college_lesson. False — не получилось."""
    from tgbot.services import sync_eios
    try:
        if date is None:
            await sync_eios.materialize(repo)
        else:
            await sync_eios.materialize_day(repo, date)
        return True
    except Exception:
        logging.exception("не удалось пересобрать college_lesson")
        return False
```

### 2. Показывать правду

В каждом из пяти вызывающих мест:

```python
ok = await _rebuild(repo)
if not ok:
    await event.answer(
        "⚠️ Правка сохранена, но расписание не пересобралось. "
        "Студенты увидят её в течение 5 минут (поллер пересоберёт сам). "
        "Если не появилась — сообщи админу.",
        reply_markup=...)
    return
```

Важно: **не откатывать правку**. Она уже в слоях и корректна; поллер
пересоберёт через ≤5 минут. Задача — не врать, а не «отменить».

### 3. Уведомление студентам — тоже проверять

`notify_group_about_edit` уже обёрнут в `try/except` и логирует. Но
староста не знает, дошло ли уведомление. Сейчас в тексте есть
`f" · уведомлено: {notified}"` — этого достаточно, если `notified`
честный. Проверить, что при полном провале он показывает 0, а не
молчит.

## Как проверить

Тест с искусственно сломанной пересборкой:

```python
def test_editor_reports_failed_rebuild(monkeypatch):
    """Провал пересборки не должен выглядеть как успех.

    Раньше _rebuild глотал исключение, и староста видел «Сохранено»,
    хотя студент ничего не получал.
    """
    async def boom(*a, **kw):
        raise RuntimeError("database is locked")
    monkeypatch.setattr(sync_eios, "materialize", boom)
    # вызвать cb_edit_base -> проверить текст ответа: есть «⚠️»
```

## Риски

- **Не сделать хуже.** Если `_rebuild` падает часто (например, из-за
  конкуренции), староста будет видеть предупреждение каждый раз.
  Это правильное поведение — оно сигнализирует о реальной проблеме
  (см. план 010 про WAL).
- **Поллер всё равно пересоберёт.** Поэтому предупреждение мягкое
  («в течение 5 минут»), а не «всё сломалось».
