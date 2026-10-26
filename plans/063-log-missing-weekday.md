# План 063: журнал правок не различает дни недели

**Приоритет:** низкий. Данные не теряются, но журнал бесполезен, когда
правок больше одной.

**Трудоёмкость:** S (~6 строк).

## Проблема

`editor.py:799` — экран «📜 Последние правки»:

```python
for e in entries:
    when = e.created_at.strftime("%d.%m %H:%M") if e.created_at else "—"
    where = e.date.strftime("%d.%m") if e.date else \
        f"{WEEKDAY_SHORT[(e.para or 1) - 1] if False else ''}".strip()
    if e.layer == "base":
        where = f"база/{e.para} пара"
    elif e.layer == "sub":
        where = f"замена {e.date.strftime('%d.%m') if e.date else ''}/{e.para} пара"
    lines.append(f"<b>{when}</b> · {where} · {e.action}")
```

Для правок базы `e.date` пустой (база повторяется каждую неделю, у неё
нет даты). Поэтому `where` перезаписывается на `f"база/{e.para} пара"` —
и **день недели и чётность пропадают**.

Правка «среда, чётная неделя, 3 пара → Физика» выглядит в журнале так:

```
26.10 14:30 · база/3 пара · edit
```

Три разные правки — понедельник/среда/пятница, все 3 пара — дадут три
одинаковые строки. Староста не может понять, какую откатывать.

## Откуда взять день

В `edit_log.new_value` он **уже сохранён**. Проверил `_save_base`
(`editor.py:467`):

```python
await repo.edit_log.log(
    group, "base", "edit" if old_slot else "add", user_id=event.from_user.id,
    para=para,
    old_value={"subject": old_slot.subject} if old_slot else None,
    new_value={"weekday": weekday, "parity": parity, "para": para,
               "subject": subject, "teacher": teacher, "room": room},
)
```

`weekday` (1–7) и `parity` (`even`/`odd`) есть. В `cb_undo` их уже
достают:

```python
new = json.loads(last.new_value) if last.new_value else {}
weekday, parity = new.get("weekday"), new.get("parity")
```

Значит в `cb_log` нужно то же самое:

```python
for e in entries:
    when = e.created_at.strftime("%d.%m %H:%M") if e.created_at else "—"
    if e.layer == "base":
        data = json.loads(e.new_value) if e.new_value else {}
        wd = data.get("weekday")
        par = PARITY_LABELS.get(data.get("parity", ""), "")
        day = WEEKDAY_SHORT[wd - 1] if wd and 1 <= wd <= 7 else "?"
        where = f"база/{day} {par}/{e.para} пара"
    elif e.layer == "sub":
        where = f"замена {e.date.strftime('%d.%m') if e.date else '?'}/{e.para} пара"
    else:
        where = f"{e.layer}/{e.para} пара"
    lines.append(f"<b>{when}</b> · {where} · {e.action}")
```

Результат: `26.10 14:30 · база/Ср чёт/3 пара · edit`.

## Заодно: мёртвая ветка

В текущем коде есть `if False`:

```python
f"{WEEKDAY_SHORT[(e.para or 1) - 1] if False else ''}"
```

Ветка не выполняется никогда, выражение всегда даёт `""`. Плюс само
присваивание бесполезно — его перезаписывают обе ветки `if/elif` ниже.
Если `layer` окажется не `base` и не `sub`, `where` останется пустой
строкой и строка журнала начнётся с `· ·`.

Проверил `edit_log.log`: `layer` приходит только `"base"` или `"sub"`
(все 8 вызовов в `editor.py`). Так что `else` недостижим — но лучше
его иметь, чем молча терять поле.

## Проверено: таблица пуста, находка теоретическая

Проверил на проде:

```
записей в schedule_edit: 0
```

Журнал правок **никогда не использовался**. Схема таблицы:

```sql
CREATE TABLE schedule_edit (
    id INTEGER NOT NULL,
    user_id BIGINT,
    "group" VARCHAR(32) NOT NULL,
    date DATE,
    para INTEGER,
    layer VARCHAR(8) DEFAULT 'base',
    action VARCHAR(8) DEFAULT 'edit',
    old_value VARCHAR(1024) DEFAULT '',
    new_value VARCHAR(1024) DEFAULT '',
    created_at DATETIME,
    PRIMARY KEY (id)
)
```

То есть никто ещё не нажал «✏️ Редактор расписания» и не сохранил
правку. Находка проявится, когда редактор начнут использовать по
настоящему.

`old_value` и `new_value` — `VARCHAR(1024)`, места хватает с запасом:
`new_value` занимает ~120 символов.

## Связанные находки

- **4** — откат не пересобирает `college_lesson` (`cb_undo` без
  `_rebuild`);
- **5** — откат теряет преподавателя и кабинет (`old_value` содержит
  только `subject`);
- **39** — правка и журнал пишутся двумя коммитами.

Этот план — про **отображение**, не про данные. Но чинить его стоит
вместе с 4 и 5: все три в `cb_undo`/`cb_log`.

## Риски

- **`json.loads` на битом `old_value`** бросит исключение. Нужен
  `try/except` — или, если журнал пуст и формат под контролем, можно
  без него. Осторожнее: в `cb_undo` (`editor.py:845`) `json.loads` уже
  вызывается без защиты — там та же уязвимость.
- **`WEEKDAY_SHORT` уже импортирован** (`editor.py:43`), новых импортов
  не нужно.
- **`PARITY_LABELS`** есть в модуле (используется в `_save_base`).
