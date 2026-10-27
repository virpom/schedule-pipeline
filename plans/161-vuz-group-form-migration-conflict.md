# План 161: группа, переехавшая из очно-заочной в очную, вешает синхронизацию вуза

> **СДЕЛАНО 27.10.2026** (коммит `414f373`).
>
> `delete` чистит и по `form == form`, и по именам входящих групп.
> `in_([])` всегда ложно, так что пустой список ведёт себя как раньше,
> а чужие формы не задеты.
>
> Воспроизвёл на схеме до правки: `IntegrityError: UNIQUE constraint
> failed: vuz_group.name` в обоих направлениях переезда.

**Приоритет:** средний. Сейчас не срабатывает (пересечения имён между
формами нет), но включится в тот день, когда вуз переведёт группу на
другую форму — и тогда расписание очной формы перестанет обновляться
совсем, молча.

**Трудоёмкость:** S (~3 строки).

## Устройство справочника

`VuzGroup` (`models/vuz_group.py`):

```python
class VuzGroup(Base):
    __tablename__ = "vuz_group"

    name: Mapped[str] = mapped_column(String(32), primary_key=True)
    faculty: Mapped[str] = mapped_column(String(16), index=True)
    course: Mapped[int] = mapped_column(Integer)
    form: Mapped[str] = mapped_column(String(16))   # full | part | extramural
```

**`name` — первичный ключ.** Одна группа может существовать только в
одной форме.

`replace_vuz_groups` (`sync_vuz.py:159-180`):

```python
async def replace_vuz_groups(repo, groups, form):
    await repo.session.execute(delete(VuzGroup).where(VuzGroup.form == form))
    for group in groups:
        repo.session.add(
            VuzGroup(name=group.name, faculty=group.faculty,
                     course=group.course, form=group.form)
        )
    await repo.session.commit()
```

Чистится **только своя форма** — так и задумано, чтобы очная и
очно-заочная не сносили друг друга.

## Что ломается

`FILES` (`sync_vuz.py:39-42`) — словарь, порядок фиксирован:

```python
FILES = {
    "full": f"{vuz.BASE_URL}/1-ochnoe.xls",
    "part": f"{vuz.BASE_URL}/2-ochno-zaochnoe.xls",
}
```

`sync_once:355-357` идёт по нему по порядку: **сначала `full`, потом
`part`**.

### Направление `full → part` — работает

```
Состояние: "ЭЭ-26-2@vuz" : form="full"
Вуз перевёл группу в очно-заочную.

1. full: delete WHERE form="full"   -> "ЭЭ-26-2" удалён
         add(full-группы)            -> его там нет
         commit OK
2. part: delete WHERE form="part"
         add(part-группы)            -> "ЭЭ-26-2" вставлен с form="part"
         commit OK
```

### Направление `part → full` — падает

```
Состояние: "ММ-24оз@vuz" : form="part"
Вуз перевёл группу на очную.

1. full: delete WHERE form="full"   -> "ММ-24оз" НЕ тронут (он part)
         add(full-группы)            -> среди них "ММ-24оз"
         commit -> IntegrityError: UNIQUE constraint failed: vuz_group.name
```

`delete` чистит только `form="full"`, а конфликтующая строка лежит с
`form="part"`. `name` — PK, вторая строка с тем же именем невозможна.

## Почему это не «просто упало и всё»

**Транзакция откатывается — данные целы.** Проверил: при выходе из
`async_sessionmaker` без `commit` всё откатывается, `vuz_group`
остаётся как был. Это хорошо.

**Но `replace_vuz_lessons` и `replace_vuz_changes` не выполняются.**
`sync_once:356` стоит вне `try`, и `replace_vuz_groups` вызывается
**первым**:

```python
await replace_vuz_groups(repo, parsed.groups, form)     # :356 упало
count = await replace_vuz_lessons(repo, parsed.lessons, form)   # не дошло
await replace_vuz_changes(repo, parsed.changes, form)           # не дошло
```

**Расписание очной формы перестаёт обновляться.** `result["full"]`
остаётся `False`, но `result["failed"]` — тоже пуст (исключение
вылетело раньше, чем туда что-то попало).

**Админ ничего не узнает.** `poller.py:86-88`:

```python
except Exception:
    logging.exception("синхронизация вуза не удалась")
```

Только лог. Это то, о чём план 016, но там речь про `VuzParseError`, а
здесь — про `IntegrityError`.

**Следующий опрос повторяет то же самое.** `part` обновляется
успешно (`full → part` не падает), справочник `part` в порядке,
`full`-группа так и остаётся с `form="part"`. Вечный цикл.

## Что сделать

**Чистить по имени, а не только по форме:**

```python
async def replace_vuz_groups(repo, groups, form):
    names = [g.name for g in groups]
    # Группа могла переехать из другой формы: её строка уже есть,
    # а name — первичный ключ. Удаляем по имени, не только по форме.
    await repo.session.execute(
        delete(VuzGroup).where(
            (VuzGroup.form == form) | (VuzGroup.name.in_(names))
        )
    )
    ...
```

Это удаляет и старые строки своей формы, и любые строки с теми же
именами из других форм. Дальше `add` проходит без конфликта.

**Проверить, что `part` не пострадает.** Если `part` обрабатывается
после `full` и его группы не пересекаются с `full` — `VuzGroup.name
.in_(names_full)` их не тронет. Если пересекаются (чего быть не
должно) — `part`-строка удалится, но её тут же вставит свой
`replace_vuz_groups(part)`.

**Не забыть про пустой список.** `names = []` даёт
`VuzGroup.name.in_([])` → условие всегда ложно, остаётся только
`form == form`. Поведение как раньше. Корректно.

## Проверено и признал корректным

**Пересечения имён между формами сейчас нет.** Распарсил оба живых
файла: `full` — 54 группы, `part` — 38, пересечение **0**. Поэтому
дефект не срабатывает.

**Удаление ушедших групп работает.** `delete WHERE form=...` перед
вставкой убирает группы, которых больше нет в файле. Проверил логику:
`add` вставляет только то, что пришло.

**Транзакция откатывается корректно.** Воспроизвёл на in-memory
SQLite: после `IntegrityError` и выхода из сессии старая строка
`('Y','full')` на месте.

**`VuzGroup.form` не входит в PK** — иначе конфликта не было бы
вовсе. Он обычная колонка, поэтому две строки с одним `name` и
разными `form` невозможны.

## Риски

- **`name.in_(names)` при большом списке.** 54–92 имени — SQLite
  спокойно. При тысячах понадобится временная таблица.
- **Порядок `FILES`** остаётся значимым: `full` первым. Если поменять
  местами, направление, в котором падает, тоже сменится — но не
  исчезнет. Правка выше снимает зависимость от порядка.
