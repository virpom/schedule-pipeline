# Что делать, когда не работает

Симптом → причина → что проверить. Сначала всегда посмотрите логи:

```bash
docker logs -f --tail=100 bot-wi188f7kradbxpz2efrl7vms
```

Имя контейнера — то, что задано в `--name` при запуске; на проде это
`bot-wi188f7kradbxpz2efrl7vms`. Своё смотрите так:
`docker ps -a --filter name=bot`.

## Бот молчит

**Проверить, что процесс жив:**

```bash
docker ps -a --filter name=bot-wi188f7kradbxpz2efrl7vms
```

Если статус `Restarting` — бот падает при старте. Смотрите логи целиком:

```bash
docker logs --tail=200 bot-wi188f7kradbxpz2efrl7vms
```

Частые причины падения при старте:

| В логах | Причина |
|---|---|
| `BOT_TOKEN` / `TokenValidationError` | токен пустой или неверный |
| `alembic` + ошибка | миграция не накатилась, схема несовместима |
| `PermissionError` на `/data` | том не смонтирован или нет прав |
| `sqlite3.OperationalError: unable to open` | `SQLITE_PATH` указывает в несуществующую папку |

**Проверить, что Telegram видит бота:**

```bash
docker exec bot-wi188f7kradbxpz2efrl7vms python -c "
import os, json, urllib.request
t = os.environ['BOT_TOKEN']
print(json.load(urllib.request.urlopen(f'https://api.telegram.org/bot{t}/getMe')))
"
```

**Проверить, что нет второго экземпляра.** Два процесса с одним токеном
дерутся за обновления, и бот отвечает через раз:

```bash
docker ps -a --filter name=bot --format '{{.Names}}\t{{.Status}}'
```

Должен быть ровно один контейнер. Второй появляется, если кто-то запустил
`docker compose up -d`: compose создаёт `schedule-bot` рядом с прод-именем.

## Расписание не обновляется

**Сначала `/stats` в боте.** Там видно состояние источника:

```
✅ ЭИОС: 24.10 01:50          ← всё хорошо, данные свежие
⚠️ ЭИОС не отвечает (успех: 24.10 01:50)   ← сайт не отвечает
```

Если `⚠️` — проблема на стороне сайта, чинить нечего, бот сам дождётся.

**Проверить сайт руками:**

```bash
docker exec bot-wi188f7kradbxpz2efrl7vms python -c "
import asyncio, sys
sys.path.insert(0, '/app')
from aiohttp import ClientSession
from parsers import eios
from config import load_config

async def main():
    cfg = load_config('.env')
    async with ClientSession() as s:
        async with s.get(cfg.schedule_url, timeout=30) as r:
            print('HTTP', r.status)
            links = eios.extract_links(await r.text())
    print('очное :', links.ochoe)
    print('замены:', links.zameny)

asyncio.run(main())
"
```

**Если `EiosParseError: структура источника изменилась`** — поменялась
разметка страницы. Ссылки ищутся по маркеру `timetable.ptk`; если сайт
переименовал папку или сменил разметку, парсер надо править. См.
[`PARSING.md`](PARSING.md).

**Если файл скачался, но данные не изменились** — так и задумано.
Дедуп по `sha256`: файл не менялся, слои не перезаписываются, рассылка
не уходит. Это норма.

**Проверить, что опрос вообще идёт:**

```bash
docker exec bot-wi188f7kradbxpz2efrl7vms python -c "
import sqlite3
c = sqlite3.connect('/data/database.db')
for k, v in c.execute(\"select key, value from setting where key like '%hash%' or key='last_sync_ok'\"):
    print(k, '=', v)
"
```

Если `last_sync_ok` пуст — ни одного успешного прохода не было.

**Ночная пауза.** С 23:00 до 07:00 опрос не идёт — так задумано.
Проверить настройки:

```bash
docker exec bot-wi188f7kradbxpz2efrl7vms python -c "
import sqlite3
c = sqlite3.connect('/data/database.db')
for k, v in c.execute(\"select key, value from setting where key in ('night_start','night_end','poll_interval')\"):
    print(k, '=', v)
"
```

## Расписание не той недели

Почти всегда — сдвиг чётности. В коде:

```python
PARITY_OFFSET = 1   # tgbot/services/schedule_layer.py
```

Чётность колледжа = ISO-неделя со сдвигом на 1. Если расписание
«съехало» на неделю, проверяется это первым. См.
[`ARCHITECTURE.md`](ARCHITECTURE.md) → «Чётность недели».

## Студент видит «Занятий нет», а пары есть

Проверьте по порядку:

1. **Правильная ли группа** у пользователя. Студент мог выбрать не ту.
2. **Есть ли пары в базе:**
   ```bash
   docker exec bot-wi188f7kradbxpz2efrl7vms python -c "
   import sqlite3, datetime
   c = sqlite3.connect('/data/database.db')
   today = datetime.date.today()
   for d, g, p, s in c.execute(
       'select date, \"group\", para, subject from college_lesson where date=? limit 10', (str(today),)):
       print(d, g, p, s)
   "
   ```
3. **Не перекрыла ли замену отмена.** В `substitution` может стоять
   `SUB_CANCEL` на эту дату — тогда «занятий нет» верно.
4. **Не поставил ли староста заметку** `no_lessons` на этот день.

## Предупреждение «сайт не отвечает»

Это не ошибка бота. Так выглядит ситуация, когда последняя успешная
синхронизация была больше 30 минут назад:

```
⚠️ Сайт колледжа не отвечает с 24.10 09:30.
Замены с тех пор не проверены — они могли появиться.
```

Расписание при этом показывается — постоянное расписание верно. Бот
честно говорит, что **замены** могли не доехать.

Если предупреждение висит, хотя сайт открывается в браузере — проверьте,
доступен ли он из контейнера (возможно, блокировка по IP или DNS):

```bash
docker exec bot-wi188f7kradbxpz2efrl7vms python -c "
import urllib.request
print(urllib.request.urlopen('https://eios.norvuz.ru/mod/page/view.php?id=49960', timeout=20).status)
"
```

## Рассылка не приходит

1. **Подписан ли пользователь.** Проверить в БД:
   ```bash
   docker exec bot-wi188f7kradbxpz2efrl7vms python -c "
   import sqlite3
   c = sqlite3.connect('/data/database.db')
   print('подписано:', c.execute('select count(*) from users where subscribed=1').fetchone()[0])
   "
   ```
2. **Было ли изменение файла.** Рассылка идёт только при смене хеша.
   Если файл на сайте тот же — сообщения не будет, и это правильно.
3. **Ночная пауза.** Ночью опрос не идёт, значит и рассылки нет.
4. **Скорость.** `notify_rate` ограничивает сообщений в секунду
   (по умолчанию 20). На 219 пользователей рассылка занимает ~11 секунд.

## Звонки не приходят

| Проверить | Как |
|---|---|
| Включены ли уведомления | `/settings` → «Уведомления» |
| Есть ли звонки в базе | `/bell` |
| Правильный ли курс | от курса зависит обед |
| Не ночь ли | ночью звонков нет |

Проверить очередь напоминаний:

```bash
docker exec bot-wi188f7kradbxpz2efrl7vms python -c "
import sqlite3
c = sqlite3.connect('/data/database.db')
print('напоминаний:', c.execute('select count(*) from bell_reminder').fetchone()[0])
"
```

## Староста не может править

1. **Выданы ли права.** Админ → «👤 Редакторы».
2. **Совпадает ли группа.** Староста правит только свою группу.
3. **Не перетёрла ли синхронизация.** Правки старосты имеют
   `source='manual'` и должны переживать перезапись. Если не переживают —
   это баг в `materialize()`.

Посмотреть правки:

```bash
docker exec bot-wi188f7kradbxpz2efrl7vms python -c "
import sqlite3
c = sqlite3.connect('/data/database.db')
for r in c.execute('select * from schedule_edit order by id desc limit 10'):
    print(r)
"
```

## Данные потерялись

Проверить объёмы:

```bash
docker exec bot-wi188f7kradbxpz2efrl7vms python -c "
import sqlite3
c = sqlite3.connect('/data/database.db')
for t in ('users','base_lesson','substitution','college_lesson','bell_schedule'):
    print(t, '=', c.execute(f'select count(*) from {t}').fetchone()[0])
"
```

Ориентир: пользователей ~220, базовых пар ~700, замен ~100,
материализованных пар ~1900–2000, звонков 23.

Если `college_lesson` пуст — вызвать материализацию вручную:

```bash
docker exec bot-wi188f7kradbxpz2efrl7vms python -c "
import asyncio, sys
sys.path.insert(0, '/app')
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from config import load_config
from infrastructure.database.repo.requests import RequestsRepo
from tgbot.services import sync_eios

async def main():
    cfg = load_config('.env')
    eng = create_async_engine(cfg.db.sqlalchemy_url())
    pool = async_sessionmaker(eng, expire_on_commit=False)
    async with pool() as db:
        n = await sync_eios.materialize(RequestsRepo(db))
        print('материализовано дней:', n)
    await eng.dispose()

asyncio.run(main())
"
```

## Восстановление из резервной копии

```bash
docker stop bot-wi188f7kradbxpz2efrl7vms
cp backup-2026-10-24.tar.gz /tmp/ && cd /tmp && tar xzf backup-2026-10-24.tar.gz
rm -rf /path/to/schedule-pipeline/data
mv data /path/to/schedule-pipeline/data
docker start bot-wi188f7kradbxpz2efrl7vms
```

Проверить после: `/stats` в боте.

## Диагностика одной командой

```bash
docker exec bot-wi188f7kradbxpz2efrl7vms python -c "
import sqlite3, datetime, os
c = sqlite3.connect('/data/database.db')
print('время в контейнере:', datetime.datetime.now())
print('TZ:', os.environ.get('TZ', 'НЕ ЗАДАН'))
print()
for t in ('users','base_lesson','substitution','college_lesson','bell_schedule'):
    print(f'{t:16}', c.execute(f'select count(*) from {t}').fetchone()[0])
print()
for k, v in c.execute('select key, value from setting order by key'):
    print(f'{k:20}', v)
"
```
