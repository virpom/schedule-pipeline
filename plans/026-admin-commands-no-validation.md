# План 026: админские команды не проверяют ввод

> **СДЕЛАНО 27.10.2026** (коммит `b2300a5`).
>
> Пять команд: окно даты для якоря, пересборка после смены якоря, проверка группы с подсказкой, суффикс `@vuz`, границы `/setpoll` 10…86400.

**Приоритет:** низкий. Чатов сейчас 0, но `/setvuzanchor` с ошибкой
сдвинет расписание **всего вуза**.

**Трудоёмкость:** S (~15 строк).

## Проблема 1: `/setvuzanchor` меняет якорь без пересборки

`admin.py:266`:

```python
await sync_vuz.set_anchor(repo, value)
await message.answer(
    f"✅ Якорь вуза: <b>{value}</b>\n\n"
    "Расписание пересоберётся на ближайшие дни при следующей синхронизации.")
```

`set_anchor` только пишет в `setting`:

```python
async def set_anchor(repo, value):
    await repo.settings.set(ANCHOR_KEY, value.isoformat())
```

`college_lesson` **не пересобирается**. Студент вуза продолжит видеть
расписание по старому якорю, пока не пройдёт поллер
(`poll_interval = 300` секунд из `DEFAULTS`, в БД ключа нет).

Пять минут — терпимо, но:
- если сайт вуза лежит, `sync_once` вернётся с `failed`, и пересборки
  не будет вообще;
- админ видит «✅ Якорь вуза» и считает, что всё применилось.

Заметить: `_rebuild` в `editor.py` для этого уже есть — надо только
вызвать.

```python
await sync_vuz.set_anchor(repo, value)
from tgbot.handlers.editor import _rebuild
await _rebuild(repo)          # пересобрать все 14 дней
```

Или, чтобы не тащить импорт хендлера в хендлер, вызвать напрямую:

```python
from tgbot.services import sync_eios
await sync_eios.materialize(repo)
```

## Проблема 2: `/setgroup` не проверяет существование группы

`admin.py:383`:

```python
group = parts[1].strip().upper()
await repo.chats.set_group(message.chat.id, message.chat.title or "", group)
await message.answer(f"Группа чата: <b>{group}</b>. Сюда будет приходить расписание.")
```

Нет проверки, что такая группа есть. Опечатка `/setgroup ДП-2б` →
сохранится `ДП-2Б` → поллер каждый день будет слать в чат
`format_no_lessons`, и админ не поймёт, почему пусто.

Сравнение с соседями по файлу: `/setvuzanchor` валидирует дату,
`/setnight` — время, `/setpoll`/`/setrate` — числа. `/setgroup` не
валидирует ничего.

```python
known = await repo.base_lessons.get_groups()
if group not in known:
    near = [g for g in known if g.startswith(group[:4])][:8]
    hint = f"\n\nПохожие: {', '.join(near)}" if near else ""
    await message.answer(f"Группы <b>{group}</b> нет в расписании.{hint}")
    return
```

В базе 129 групп: 37 колледжа (`ДП-26`, `ПРф-23`, …) и 92 вуза
(`АП-23@vuz`, …). Подсказка по префиксу помогает при опечатке в
последнем символе.

## Проблема 3: `/setgroup` для вуза требует суффикс

Группы вуза хранятся как `АП-23@vuz`. Админ, который введёт
`/setgroup АП-23`, получит «группы нет» после правки из п.2 — но
сейчас получит молча неверную запись. Если чинить п.2, стоит добавить:

```python
if group not in known and f"{group}@vuz" in known:
    group = f"{group}@vuz"
```

## Проблема 4: `/setpoll` без верхней границы

`admin.py:321`:

```python
sec = int(parts[1])
if sec < 10:
    raise ValueError
```

Нижняя граница есть (10 с), верхней нет. `/setpoll 999999999` примется,
и `poller_loop` больше никогда не опросит сайт:

```python
if time.monotonic() - last_poll >= interval:   # никогда не True
```

Расписание замрёт молча: `/stats` будет показывать растущую давность,
но админ, который сам ввёл число, не свяжет это с командой.

Соседний `/setrate` валидирует обе границы (`0 < rate <= 30`) — здесь
симметрию потеряли.

```python
if not 10 <= sec <= 86400:
    await message.answer("Интервал — от 10 секунд до суток (86400)")
    return
```

## Проблема 5: `/setvuzanchor` принимает любую дату

`datetime.date.fromisoformat` проверяет формат, но не смысл.
`/setvuzanchor 1999-01-01` примется — и `vuz_week` вернёт номер
недели вроде 1400, ни одна пара не совпадёт, расписание вуза опустеет.

Дешёвая проверка — якорь должен быть в разумном окне:

```python
today = datetime.date.today()
if not (today - datetime.timedelta(days=400) <= value <= today + datetime.timedelta(days=400)):
    await message.answer("Якорь должен быть в пределах учебного года от сегодня.")
    return
```

Заметить: `anchor_fit` в `sync_vuz` уже умеет ловить уехавший якорь
по датам замен, но срабатывает только при следующей синхронизации и
только пишет в лог (`logging.error`), а не отвечает админу.

## Как проверить

```python
def test_setgroup_rejects_unknown():
    """Опечатка в группе не должна создавать чат-призрак."""

def test_setvuzanchor_rebuilds():
    """Смена якоря должна сразу пересобрать college_lesson."""
```

Вживую: `/setgroup НЕТ-ТАКОЙ` → должно ответить «группы нет», а не
«✅ Группа чата».

## Риски

- **`materialize` блокирует на 3.58 с** (план 008). При смене якоря
  это приемлемо — операция редкая.
- **Не ломать существующие чаты.** Сейчас их 0, но проверка
  `group in known` не даст создать новый с опечаткой; уже созданные
  (если появятся) она не тронет.
- **Группа может исчезнуть из файла.** Если группу убрали из
  расписания, а чат на неё настроен — `/setgroup` перестанет её
  принимать. Это правильно (сигнал админу), но стоит понимать.
