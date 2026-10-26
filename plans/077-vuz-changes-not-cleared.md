# План 077: замены вуза не стираются, если файл пришёл без них

**Приоритет:** средний. Замены, которых уже нет, продолжают применяться
к расписанию вуза. Обнаружить это можно только глазами — никакого
сигнала нет.

**Трудоёмкость:** S (три строки).

## Проблема

`replace_vuz_changes` (`sync_vuz.py:183`) выходит **до** удаления старых
записей:

```python
async def replace_vuz_changes(repo, changes, form) -> int:
    """Записать замены, найденные внутри файла расписания."""
    from infrastructure.database.models import Substitution

    if not changes:
        return 0                      # <- ВЫХОД ДО УДАЛЕНИЯ
    own_groups = [...]
    manual = [...]
    manual_keys = {...}

    if own_groups:
        await repo.session.execute(
            delete(Substitution).where(
                Substitution.source == SOURCE_VUZ,
                Substitution.group.in_(own_groups),
            )
        )
    ...
```

Сравнить с коллегой из `sync_eios.py:111` — там та же задача решена
иначе:

```python
async def replace_substitutions(repo, subs) -> int:
    """Заменить замены, пришедшие с сайта. Ручные не трогаем."""
    manual = [...]
    manual_keys = {...}

    await repo.session.execute(              # <- УДАЛЕНИЕ ВСЕГДА
        delete(Substitution).where(Substitution.source == SOURCE_SITE)
    )

    for sub in subs:                         # <- пустой список просто
        ...                                  #    ничего не добавит
```

То есть колледж при пустом листке замен чистит всё, а вуз — нет.

## Сценарий

```
День 1  вуз выложил файл с 10 заменами на ноябрь
        replace_vuz_changes(changes=[10 штук]) -> записаны

День 2  вуз перевыложил файл, замены убрал (перенёс в основное поле)
        replace_vuz_changes(changes=[]) -> return 0
        СТАРЫЕ 10 ЗАМЕН ОСТАЛИСЬ В БАЗЕ
```

`get_day_slots` применит их к расписанию: студент увидит замену, которой
в файле уже нет.

## Что показывает прод

```
замены вуза в прошлом (до 26.10):  101
замены вуза в будущем:              52
самые ранние:
  2022-11-06   2   <- опечатка года в файле
  2026-09-25   1
  2026-09-29   8
  2026-09-30   1
  2026-10-03   4
```

Сто одна просроченная запись накопилась. Сама по себе она безвредна —
`get_day_slots` фильтрует по конкретной дате, а `get_dates(today)`
отсекает прошлое. Но она показывает, что **ничего не удаляется**, и
будущие 52 замены при обнулении файла тоже останутся.

## Что сделать

Убрать ранний выход — перенести проверку после удаления, как в
`sync_eios`:

```python
async def replace_vuz_changes(repo, changes, form) -> int:
    from infrastructure.database.models import Substitution

    own_groups = [
        g for (g,) in await repo.session.execute(
            select(VuzGroup.name).where(VuzGroup.form == form)
        )
    ]

    manual = [...]
    manual_keys = {(r.date, r.group, r.para) for r in manual}

    if own_groups:
        await repo.session.execute(
            delete(Substitution).where(
                Substitution.source == SOURCE_VUZ,
                Substitution.group.in_(own_groups),
            )
        )
    else:
        await repo.session.execute(
            delete(Substitution).where(Substitution.source == SOURCE_VUZ)
        )

    now = datetime.datetime.now()
    seen: set[tuple] = set()
    added = 0
    for change in changes:            # пустой список — цикл не выполнится
        ...
    await repo.session.commit()
    return added + len(manual)
```

Важно: `if not changes: return 0` **до** `own_groups` экономил два
запроса. Убрав его, мы делаем их на каждом прогоне. Но `sync_vuz`
вызывается только когда хеш файла изменился (см. `_HASH_KEY`), то есть
раз в сутки, — экономить нечего.

## Второй дефект в той же функции: имя `manual` врёт

```python
manual = [
    row for (row,) in await repo.session.execute(
        select(Substitution).where(Substitution.source != SOURCE_VUZ)
    )
]
```

`source != 'vuz'` — это не «ручные», а «всё, что не вуз»: замены
колледжа (`source='site'`) **и** ручные. Переменная называется
`manual`, хотя содержит в основном чужие данные.

Последствий нет: ключ `(date, group, para)`, а группы вуза всегда с
суффиксом `@vuz` — `ЭК-24` и `ЭК-24@vuz` не совпадут. Проверил на
проде: точных коллизий `date+group+para` между источниками **ноль**,
хотя группы-двойники существуют (`ЭК-23`, `ЭК-24`, `ЭК-25` есть и в
колледже, и в вузе).

Но имя вводит в заблуждение при чтении. Стоит переименовать в
`foreign` или сузить условие до `source == SOURCE_MANUAL`.

## Проверено и признано корректным

**`vuz_week` до якоря даёт 0 или отрицательное.** Проверил:
`2026-08-24 -> 0`, `2026-06-01 -> -12`. Это не ошибка: якорь —
начало семестра, а `get_day_slots` проверяет `week in weeks`, где
списки содержат только положительные номера. До якоря пар и не должно
быть.

**`anchor_looks_off` защищён от малых выборок.** `total >= 10 and
good * 2 < total` — при нуле или одной замене тревоги не будет. Верно:
на двух датах статистики нет.

**`VuzGroup.name` хранится с суффиксом `@vuz`.** Проверил докстринг
модели: «Имя хранится с суффиксом `@vuz`: группы вуза и колледжа живут
в одних таблицах, и `ЭК-23` у них — разные люди». Значит
`delete(...group.in_(own_groups))` не заденет колледж.

**`replace_vuz_lessons` возвращает завышенное число.** `return added +
len(manual)`, где `manual` — строки всех форм. Для формы `full` и
`part` в счётчик попадут одни и те же ручные записи. Но число идёт
только в `log.info("расписание вуза (%s) обновлено: %d пар")` — на
поведение не влияет. Косметика, отдельного плана не заслуживает.

**Ручные правки вуза сохраняются.** `manual_keys` содержит ключи с
`weeks`, и в цикле строка пропускается, если такой ключ уже есть. Логика
та же, что в `sync_eios`, и она работает.

## Риски

- **Удаление перед вставкой в одной транзакции.** `delete` и `add`
  идут до `commit()`, поэтому при падении между ними откатится всё.
  Это уже так работает — правка не меняет поведение.
- **Форма без групп.** Если `own_groups` пуст (справочник ещё не
  залит), код удаляет **все** замены вуза. Ветка `else` существовала и
  раньше, но раньше она не достигалась при пустом `changes`. Теперь
  достижима. На проде `vuz_group` заполнен (92 группы), так что ветка
  не сработает, но при первом запуске на чистой базе — сработает.
  Стоит либо не трогать `else`, либо убедиться, что
  `replace_vuz_groups` вызывается раньше — он вызывается
  (`sync_vuz.py:353`), так что `own_groups` будет непуст.
