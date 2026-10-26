# План 143: редактору можно дать группу вуза, и правки на ней ломаются

**Приоритет:** средний. Сейчас права выданы только на `ДП-26`
(колледж), но список предлагает 92 группы вуза из 129 — админ
ошибится на первом же неверном нажатии.

**Трудоёмкость:** S (~5 строк).

## Проблема 1: список групп не фильтрует вуз

`_ask_group` (`admin.py:1206`) собирает кнопки из **обоих** источников:

```python
base_groups = await repo.base_lessons.get_groups()
site_groups = await repo.college_lessons.get_groups()
groups = sorted(set(base_groups) | set(site_groups))
```

`get_groups()` возвращает **все** группы, включая `@vuz`. Проверил:

```
всего групп в списке:  129
  из них @vuz:          92 (71%)
  колледжных:           37
```

То есть **71% кнопок — группы вуза**. Показываются по три в ряд, 43
ряда.

## Что будет, если выдать права на группу вуза

Редактор откроет её, увидит пары (`get_day` их отдаёт), попробует
удалить — и **ничего не произойдёт**, хотя бот ответит «Убрано».

`cb_del_base` (`editor.py:508`):

```python
await repo.base_lessons.delete_slot(group, parity, weekday, para)
```

`delete_slot` (`base_lesson.py:92`):

```python
async def delete_slot(self, group: str, parity: str, weekday: int, para: int,
                      weeks: str = "") -> None:
    await self.session.execute(
        delete(BaseLesson).where(
            ...
            BaseLesson.weeks == weeks,   # <- "" по умолчанию
        )
    )
```

А у групп вуза `weeks` **не пустой**:

```
base_lesson: 2659 строк
  с weeks != "":  1340 — все @vuz
  колледжных с weeks != "":  0
```

`DELETE` не найдёт ни одной строки, `commit()` пройдёт молча,
`_rebuild` пересоберёт то же самое, и человек увидит «🗑 Пара убрана»
с парой на прежнем месте.

## Проблема 2: откат удаления вообще не восстанавливает

Даже для колледжа. `cb_del_base` (`:509`) не передаёт `new_value`:

```python
await repo.edit_log.log(
    group, "base", "delete", user_id=cb.from_user.id, para=para,
    old_value={"subject": old_slot.subject} if old_slot else None,
)
```

А `cb_undo` (`:843`) берёт день недели и чётность **из `new_value`**:

```python
new = json.loads(last.new_value) if last.new_value else {}
weekday, parity = new.get("weekday"), new.get("parity")
```

Раз `new_value` — `NULL`, `weekday` и `parity` будут `None`. Дальше:

```python
elif old.get("subject"):
    if weekday and parity:          # False — молча пропускаем
        await repo.base_lessons.upsert(...)
    msg = f"↩️ Возвращено: <b>{old['subject']}</b>"   # но сообщаем об успехе
```

**Пара не восстановлена, а человеку сказали «Возвращено».** И запись
из журнала удалена — повторить попытку нельзя.

## Почему это хуже, чем кажется

Оба дефекта дают **ложный успех**: интерфейс говорит, что всё
получилось, а данные не изменились. Человек узнает правду, только
когда студенты пожалуются — или никогда.

## Что сделать

**1. Отфильтровать вуз из списка групп:**

```python
from common.schedule import is_vuz
groups = [g for g in sorted(set(base_groups) | set(site_groups))
          if not is_vuz(g)]
```

Редактор вуза не предусмотрен: `base_lesson` вуза разложен по неделям
(`weeks`), а интерфейс редактора знает только чётность. Поддержать это
— отдельная работа, не для этой правки.

**2. Записывать день и чётность при удалении:**

```python
await repo.edit_log.log(
    group, "base", "delete", user_id=cb.from_user.id, para=para,
    old_value={"subject": old_slot.subject,
               "teacher": old_slot.teacher,
               "room": old_slot.room} if old_slot else None,
    new_value={"weekday": weekday, "parity": parity, "para": para},
)
```

**3. Не врать при неудаче.** Если восстановить нельзя — сказать прямо:

```python
elif old.get("subject") and weekday and parity:
    await repo.base_lessons.upsert(...)
    msg = f"↩️ Возвращено: <b>{old['subject']}</b>"
else:
    msg = "↩️ Восстановить не удалось: в журнале нет дня недели"
```

## Что проверил и признал корректным

**`delete_slot` для колледжа работает.** У всех 704 колледжных строк
`weeks = ""`, что совпадает с дефолтом. Дефект только на вузе.

**`get_day` вуза не падает.** Без `week` возвращает все строки слота,
не теряя пары — комментарий это объясняет. Чтение корректно, ломается
только удаление.

**Права выданы безопасно.** Проверил `schedule_editor`: 2 строки, обе
на `ДП-26` (колледж), `active=1`. До вуза дело не дошло.

**`_ask_group` не даёт ввести группу текстом** — только кнопки. Значит
опечатки невозможны, но и промахнуться легко: 92 кнопки подряд.

## Риски

- **Скрыть 92 кнопки** сократит список с 129 до 37 — это заметно
  улучшит навигацию, но если вуз когда-нибудь понадобится, придётся
  возвращать с поддержкой `weeks`.
- **`old_value` расширяется до трёх полей** — `_dump` режет на 1024
  символах, запас большой.
