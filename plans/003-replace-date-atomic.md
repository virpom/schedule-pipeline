# План 003: `replace_date` не должен оставлять день пустым

**Приоритет:** третий. Тот же класс потери данных, что и план 001, но
через другой путь. Правка — две строки.

**Трудоёмкость:** S (~10 строк + 1 тест).

## Проблема

`infrastructure/database/repo/college_lesson.py:32`:

```python
async def replace_date(self, date: datetime.date, lessons: list[dict]) -> None:
    await self.session.execute(delete(CollegeLesson).where(CollegeLesson.date == date))
    await self.session.commit()          # <-- коммит №1
    await self.bulk_insert(lessons)      # <-- коммит №2 внутри
```

Два независимых коммита. Если вставка упадёт после первого, день
останется **пустым** — delete уже зафиксирован.

**Доказано на копии боевой БД:**

```
строк за 2026-10-27 ДО: 293
вставка упала: CompileError
строк за 2026-10-27 ПОСЛЕ: 0
*** день остался ПУСТЫМ — delete закоммичен, insert нет ***
```

Вставка реально падала: комментарий в
`infrastructure/database/models/college_lesson.py` говорит, что
«наложение двух пар вуза роняло материализацию только на проде».
Нарушение `uc_college_lesson` (UNIQUE по `date, group, para`) — самый
вероятный сценарий.

Сейчас в проде все 20 дат заполнены (минимум 18 групп), то есть риск
не реализовался. Но он есть.

## Почему это хуже, чем кажется

`materialize` вызывает `replace_date` **14 раз подряд** — по одному на
день. Падение на 8-м дне оставит:

- дни 1–7 перезаписаны (нормально),
- день 8 пуст,
- дни 9–14 не тронуты (старые данные).

`_rebuild` в редакторе ловит `Exception` и пишет в лог — староста видит
«Сохранено» (см. план 009).

## Что сделать

### 1. Убрать промежуточный коммит

В `replace_date`:

```python
async def replace_date(self, date: datetime.date, lessons: list[dict]) -> None:
    await self.session.execute(delete(CollegeLesson).where(CollegeLesson.date == date))
    if lessons:
        await self.session.execute(insert(CollegeLesson).values(lessons))
    await self.session.commit()
```

Один коммит в конце. Это ровно тот приём, что уже применён в
`sync_eios.replace_base_lessons` (строки 77–108): delete и insert
копятся в сессии, commit один. Там он работает и покрыт тестами.

### 2. Оставить `bulk_insert` для других вызывающих

`bulk_insert` используется ещё в одном месте — проверить:

```bash
grep -rn "bulk_insert" --include=*.py .
```

Если вызов только из `replace_date`, его можно оставить как есть
(публичный метод, не мешает). Если хочется чище — сделать
`bulk_insert(..., commit=False)` с параметром, но это уже лишнее.

### 3. Тест на атомарность

В `tests/test_sync_eios.py` (там уже есть харнесс):

```python
def test_replace_date_keeps_data_on_insert_failure():
    """Падение вставки не должно оставлять день пустым.

    Раньше delete коммитился отдельно от insert: упавшая вставка
    оставляла день без пар, и студент видел «Занятий нет».
    """
    async def scenario():
        engine, pool = await make_env()
        try:
            async with pool() as db:
                repo = RequestsRepo(db)
                good = [{"date": d, "group": "ДП-26", "para": 1, ...}]
                await repo.college_lessons.replace_date(d, good)
                before = await repo.college_lessons.get_for_group_date("ДП-26", d)
                assert before

                bad = [{**good[0], "НЕТ_ТАКОЙ_КОЛОНКИ": 1}]
                with pytest.raises(Exception):
                    await repo.college_lessons.replace_date(d, bad)

                after = await repo.college_lessons.get_for_group_date("ДП-26", d)
                assert after == before, "данные дня потеряны при падении вставки"
        finally:
            await engine.dispose()
    run(scenario())
```

Ключевой ассерт — `after == before`. До правки он упадёт.

## Как проверить

```bash
.venv/bin/python -m pytest tests/test_sync_eios.py -q
```

Плюс повторить замер на копии БД: полная пересборка должна остаться
быстрой (сейчас 3.58 с; станет чуть быстрее — минус 14 коммитов).

## Риски

- **Размер транзакции.** Сейчас на день ~280 строк. Одна транзакция на
  день вместо двух — это нормально для SQLite.
- **`bulk_insert` без `commit`.** Если он используется где-то ещё без
  последующего коммита, данные молча не запишутся. Проверить `grep`
  перед правкой.
- **Не путать с `replace_base_lessons`** — там уже атомарно, трогать
  не нужно.
