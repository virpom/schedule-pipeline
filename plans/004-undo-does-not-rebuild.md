# План 004: откат правки должен доходить до студента

> **СДЕЛАНО 27.10.2026** (коммит `3d7f632`).
>
> `cb_undo` вызывает `_rebuild` после отката обеих веток. Тест `tests/test_undo_rebuild.py`.

**Приоритет:** четвёртый. Староста видит «Откачено», студент — старое
расписание. Тот же класс регрессии, что чинили 25.10 для сохранения.

**Трудоёмкость:** S (~5 строк + 1 тест).

## Проблема

`tgbot/handlers/editor.py:830` `cb_undo` меняет слои, но **не вызывает
`_rebuild`**:

```python
if last.layer == "base":
    ...
    await repo.base_lessons.delete_slot(group, parity, weekday, last.para)
    ...
else:
    await repo.substitutions.delete(last.date, group, last.para)
    ...

await repo.edit_log.delete(last.id)
await cb.answer(msg, show_alert=True)
await cb_log(cb, repo)          # <-- и всё
```

Сравнить с любым другим обработчиком правки:

| Обработчик | `_rebuild` |
|---|---|
| `cb_edit_base` (строка 474) | ✅ `_rebuild(repo)` |
| `cb_del_base` (строка 513) | ✅ `_rebuild(repo)` |
| `cb_sub_cancel` (строка 619) | ✅ `_rebuild(repo, date)` |
| `cb_sub_reset` (строка 633) | ✅ `_rebuild(repo, date)` |
| `cb_sub_edit` (строка 725) | ✅ `_rebuild(repo, date)` |
| **`cb_undo` (строка 830)** | ❌ **нет** |

Студент читает `college_lesson`, а не слои. Без пересборки откат
доедет до него только через следующий проход поллера — до 5 минут.

## Что сделать

### 1. Вызвать `_rebuild` с правильной областью

Для `base` — все дни (правка повторяется каждую неделю), для `sub` —
только тот день:

```python
    if last.layer == "base":
        ...
    else:
        await repo.substitutions.delete(last.date, group, last.para)
        msg = "↩️ Замена снята"

    await _rebuild(repo, None if last.layer == "base" else last.date)
    await repo.edit_log.delete(last.id)
```

Порядок: `_rebuild` **до** `edit_log.delete`, чтобы при падении отката
запись в журнале осталась и староста мог повторить.

### 2. Тест, который зовёт настоящий обработчик

Существующий `tests/test_edit_undo.py` **дублирует** логику вместо
вызова — в нём прямо написано:

```python
# Откат: удаляем пару (то, что теперь делает cb_undo).
await repo.base_lessons.delete_slot("ДП-26", "ANY", 1, 1)
```

Поэтому тест остаётся зелёным, даже если `cb_undo` сломан. Переписать
его так, чтобы он вызывал `editor.cb_undo` с поддельным `CallbackQuery`
(образец — `tests/test_admin_stats.py`, там уже так делают).

Проверять надо не журнал, а `college_lesson`:

```python
def test_undo_rebuilds_college_lesson():
    """После отката студент должен сразу видеть старое расписание.

    Раньше cb_undo менял слои, но не пересобирал college_lesson —
    студент видел правку до следующего опроса поллера.
    """
    # 1. подготовить base_lesson + materialize
    # 2. вызвать editor.cb_undo(...)
    # 3. проверить college_lesson: пара вернулась/исчезла
```

### 3. Заодно исправить `old_value` (см. план 005)

`cb_undo` для `base` читает `old.get("teacher", "")` и
`old.get("room", "")`, но обработчики пишут только `subject`. Значит
откат **всегда** теряет преподавателя и кабинет. Это отдельный план,
но правки в одном файле — делать вместе.

## Как проверить

```bash
.venv/bin/python -m pytest tests/test_edit_undo.py -q
```

Вживую: староста правит пару → «Откатить» → студент открывает «Сегодня»
и сразу видит старое значение, без ожидания.

## Риски

- **Двойная пересборка.** Если `_rebuild` уже вызывался где-то выше по
  стеку — проверить, что нет. В `cb_undo` его нет ни в одной ветке.
- **`last.date` может быть `None`** для `base`-правок. Поэтому
  `_rebuild(repo, None)` — правильно: пересобирает все дни.
