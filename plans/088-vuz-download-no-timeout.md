# План 088: скачивание вуза без таймаута — проход может встать на 10 минут

**Приоритет:** средний. Не теряет данные, но задерживает рассылку и
следующий опрос, а причину в логах не видно.

**Трудоёмкость:** S (одна строка + 1 тест).

## Проблема

Две функции с одинаковым именем и назначением, в соседних модулях:

`tgbot/services/sync_eios.py:195` — **с таймаутом**:
```python
async def _download(session: ClientSession, url: str) -> bytes:
    async with session.get(url, raise_for_status=True, timeout=60) as response:
        return await response.read()
```

`tgbot/services/sync_vuz.py:307` — **без**:
```python
async def _download(session: ClientSession, url: str) -> bytes:
    async with session.get(url) as response:
        response.raise_for_status()
        return await response.read()
```

Разница не случайна только по виду: `sync_eios` передаёт
`raise_for_status=True` в `get`, `sync_vuz` вызывает метод отдельно. Но
главное — пропущенный `timeout=60`.

## Что подставляется вместо таймаута

`ClientSession` создаётся без явного таймаута (`poller.py:64`):

```python
async with ClientSession() as session:
```

Проверил, что реально получается в aiohttp 3.10.11:

```
aiohttp.ClientTimeout()      -> total=None, connect=None, sock_read=None
ClientSession()._timeout     -> total=300
```

То есть `ClientSession` подставляет **свой** дефолт — 300 секунд на весь
запрос. Пустой `ClientTimeout()` тут ни при чём, сессия его не берёт.

**300 секунд на файл** — это не «защита», а «пять минут тишины».

## Худший случай

```
sync_vuz.sync_once:
  full  -> _download   до 300 с
  part  -> _download   до 300 с
                        -----------
                        до 600 с = 10 минут

затем sync_eios.sync_once:
  _fetch_links    60 с
  ochoe           60 с
  zameny          60 с
  bells_monday    60 с
  bells_standard  60 с
                        -----------
                        до 300 с = 5 минут
```

`poll_once` — **до 15 минут в одном вызове**. Всё это время
`poller_loop` стоит на `await poll_once(...)` и не доходит ни до
`notify_new_schedule`, ни до следующего опроса.

Звонки и хендлеры при этом работают: `bell_loop` — отдельная задача,
aiogram — в том же event loop. Но новое расписание не рассылается, пока
висящий запрос не истечёт.

## Почему это хуже, чем «просто медленно»

Сайт вуза (`norvuz.ru`) — внешний, и когда он начинает отдавать
соединение по капле, aiohttp держит запрос до 300 секунд. В логах за это
время **ничего**: `_download` не логирует ни начала, ни прогресса.

Админ видит, что расписание не обновилось, и не может отличить:

- сайт лежит (соединение не устанавливается — это быстро, `connect`
  тоже 300 с, но обычно падает раньше);
- сайт отдаёт медленно (запрос висит);
- бот завис.

Таймаут `60` в `sync_eios` — ровно то, что надо: за минуту видно, что
не вышло.

## Что сделать

Скопировать приём соседа:

```python
async def _download(session: ClientSession, url: str) -> bytes:
    async with session.get(url, raise_for_status=True, timeout=60) as response:
        return await response.read()
```

Одна строка. Заодно уходит разница в стиле (`raise_for_status` в
`get` против отдельного вызова).

**Лучше** — вынести общий хелпер, раз функций уже две:

```python
# tgbot/services/http.py
async def download(session, url: str, timeout: int = 60) -> bytes: ...
```

Тогда третья копия не появится. Но это уже рефакторинг; для правки
дефекта хватает первой строки.

## Проверено и признано корректным

**`sync_eios` таймаут соблюдает.** Все пять запросов идут через
`_download` с `timeout=60` — проверил `grep -rn "session.get"`, других
мест нет.

**`ClientSession` не переиспользуется между проходами.** `poll_once`
открывает свою сессию на вызов и закрывает в `async with` — утечки
соединений нет.

**Ошибки скачивания в вузе не роняют проход.** `sync_once` ловит
исключение вокруг `_download`:

```python
try:
    data = await _download(session, url)
except Exception as exc:
    log.warning("не удалось скачать %s: %s", url, exc)
    result["failed"].append(form)
    continue
```

То есть таймаут даст `asyncio.TimeoutError`, попадёт в `failed`, форма
пропустится, вторая попробуется. Механизм готов — не хватает только
самого таймаута.

**`failed` доходит до админа?** Нет — [план 016](016-vuz-failures-silent.md).
Здесь только про задержку.

## Риски

- **`timeout=60` может оказаться мал для большого файла.** Проверил
  прод: `1-ochnoe.xls` и `2-ochno-zaochnoe.xls` качаются за секунды
  (парсинг 1314 пар занимает больше времени, чем загрузка). 60 секунд
  с запасом. Если файл вырастет в разы — поднять до 120.
- **Правка не влияет на корректность данных.** Только на то, как быстро
  проход сдаётся.
