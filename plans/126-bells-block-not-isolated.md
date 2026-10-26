# План 126: блок звонков не изолирован — его падение теряет уведомления

**Приоритет:** средний. Сейчас звонки живы (200), но конструкция
несимметрична: три из четырёх шагов защищены, четвёртый нет.

**Трудоёмкость:** S (~10 строк).

## Проблема

`sync_once` (`sync_eios.py:227`) оборачивает шаги в локальный `_step`:

```python
async def _step(name: str, coro) -> None:
    try:
        await coro
    except Exception as exc:  # noqa: BLE001
        log.warning("не удалось обновить %s: %s", name, exc)
        failed.append(name)
```

Так сделано для двух шагов:

```python
if links.ochoe:
    await _step("очное расписание", _sync_ochoe(...))       # :254

if links.zameny:
    await _step("замены", _sync_zameny(...))                # :258
```

А блок звонков (`:259-278`) — **без обёртки**:

```python
slots = []
if links.bells_monday:
    data = await _download(session, links.bells_monday)     # :263 <- бросит
    slots += await asyncio.to_thread(eios.parse_bells, data, "MONDAY")
if links.bells_standard:
    data = await _download(session, links.bells_standard)   # :266 <- бросит
    slots += await asyncio.to_thread(eios.parse_bells, data, "OTHER")
```

`_download` (`:195`) поднимает исключение на любой ошибке:

```python
async with session.get(url, raise_for_status=True, timeout=60) as response:
```

## Что произойдёт при 404 на звонках

Исключение вылетит из `sync_once` целиком. Поллер поймает его в
`poller.py:91`:

```python
except Exception as e:
    logging.warning("ЭИОС недоступен: %s", e)
    result = None
    await _report_failure(bot, session_pool, config, e)
```

**Дальше — важное.** К этому моменту `_sync_ochoe` уже отработал:
записал `base_lesson`, обновил `eios_hash_ochoe`, поставил
`changed["ochoe"] = True`. Но `result` станет `None`, и словарь
`changed` **потеряется**.

Последствие в `poller.py:143`:

```python
if not changes:
    return
```

`changes` пуст → `notify_new_schedule` не вызывается → **никто не узнает,
что расписание обновилось**, хотя в базе оно уже новое.

## Чем это отличается от плана 105

План 105 — про замены: `_step` ловит ошибку, `failed` заполняется,
`mark_ok` не зовётся, студенты видят ложное «сайт не отвечает».
Там **данные целы**, страдает только предупреждение.

Здесь другое: **теряется уведомление об уже применённом изменении**.
Студент увидит новое расписание, только если сам откроет бота. Ни
рассылки, ни повода её ждать.

## Что сделать

Обернуть блок звонков так же, как остальные:

```python
async def _bells() -> None:
    slots = []
    if links.bells_monday:
        data = await _download(session, links.bells_monday)
        slots += await asyncio.to_thread(eios.parse_bells, data, "MONDAY")
    if links.bells_standard:
        data = await _download(session, links.bells_standard)
        slots += await asyncio.to_thread(eios.parse_bells, data, "OTHER")
    if not slots:
        return
    digest = hashlib.sha256(...).hexdigest()
    if force or await repo.settings.get(_HASH_KEY.format(kind="bells")) != digest:
        count = await replace_bells(repo, slots)
        await repo.settings.set(_HASH_KEY.format(kind="bells"), digest)
        log.info("звонки обновлены: %d слотов", count)
        changed["bells"] = True

await _step("звонки", _bells())
```

Тогда падение звонков попадёт в `failed`, `changed` сохранится, и
уведомление об очном расписании уйдёт.

## Почему это реально, а не теория

Звонки — **два отдельных файла**, и оба качаются на каждом проходе
(`_download` вызывается до проверки хеша — хеш считается по
содержимому). Сайт уже показал, что умеет удалять файлы, оставляя
ссылку: именно это случилось с `Листок замен.docx` в 15:53 сегодня.

Проверил сейчас:

```
bells_monday    200  16032 байт
bells_standard  200  15989 байт
zameny          404  162 байта (nginx)
```

Пока живы. Но если завтра пропадёт `понедельник.docx`, бот потеряет
не звонки, а **уведомления обо всём расписании**.

## Проверено и признал корректным

**`_step` работает правильно.** Ловит `Exception` (не `BaseException`),
логирует с именем шага, копит `failed`. Хорошая конструкция — её и
надо применить к четвёртому шагу.

**`failed` попадает в результат** (`:280`):

```python
if failed:
    changed["failed"] = failed
```

**Порядок шагов разумен:** очное → замены → звонки. Очное первым,
потому что от него зависит материализация.

**Материализация вызывается всегда** (`poller.py:113`), даже при сбое —
комментарий объясняет: окно дат должно сдвигаться, иначе через две
недели расписание «кончится».

## Риски

- **Правка затрагивает `sync_once` — сердце синхронизации.** Ошибка в
  ней ломает всё обновление. Проверять на копии, не на боевой.
- **`_step` принимает уже созданную корутину.** Если обернуть вызов
  напрямую (`_step("звонки", _bells())`), корутина создастся до входа
  в `try` — но исключение возникнет при `await`, внутри `try`, так что
  это безопасно. Именно так уже сделано для `_sync_ochoe`.
