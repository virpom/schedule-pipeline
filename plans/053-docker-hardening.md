# План 053: контейнер от root, без healthcheck, а compose не используется

> **СДЕЛАНО 27.10.2026** (коммит `b79f3a9`). Отметка стояла в
> `plans/README.md`, но не в файле плана.

**Приоритет:** низкий. Всё работает, но деплой держится на ручных
командах, а сбой бота не виден снаружи.

**Трудоёмкость:** S (~10 строк).

## 1. Контейнер работает от root

`Dockerfile` целиком:

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt
COPY . .
CMD ["python", "main.py"]
```

Директивы `USER` нет. Проверил на проде:

```
docker exec ... id
uid=0(root) gid=0(root) groups=0(root)
```

**Последствия видны уже сейчас.** Каталог `/data` принадлежит
`virprom:virprom` (это хостовый `./data`):

```
drwxrwxr-x 3 virprom virprom  4096 окт 25 23:59 .
-rw-r--r-- 1 root    root    2158592 окт 25 23:59 database.db
-rw-r--r-- 1 virprom virprom 270336  окт 16 23:35 database.backup-...db
-rw-r--r-- 1 root    root     950272 окт 24 11:02 copy-test.db
```

Файлы, созданные контейнером, принадлежат **root** и лежат в папке
пользователя. Скопировать или удалить их без `sudo` нельзя — что и
произошло с `copy-test.db`, который так и остался висеть с 24 октября.

Риск: если бот когда-нибудь начнёт писать что-то за пределы `/data`
(лог-файл, временный экспорт), это тоже ляжет root-ом. И при
компрометации бота через парсер xlsx/docx атакующий получает root
внутри контейнера — а с текущей настройкой это ещё и root на
смонтированном каталоге.

## 2. Нет healthcheck

Ни в `Dockerfile`, ни в `docker-compose.yml` нет `HEALTHCHECK`.
Проверил прод:

```
docker ps -> "Up 2 hours"
```

Статус `Up` означает «процесс жив», а не «бот отвечает на сообщения».
Если `dp.start_polling` зависнет (сеть, блокировка на long-poll), а
процесс останется — Docker будет считать контейнер здоровым
бесконечно.

Для этого бота простейшая проверка — свежесть `last_sync_ok`:

```dockerfile
HEALTHCHECK --interval=5m --timeout=10s --start-period=2m --retries=3 \
  CMD python -c "import sqlite3,sys,datetime; \
      c=sqlite3.connect('/data/database.db'); \
      r=c.execute(\"select value from setting where key='last_sync_ok'\").fetchone(); \
      sys.exit(0 if r and r[0] else 1)"
```

Осторожно: ночью поллер спит, `last_sync_ok` не обновляется с 23:00 до
07:00 — healthcheck начнёт «падать» каждую ночь. Нужен порог с учётом
ночного окна (та же проблема, что в плане 049).

## 3. `docker-compose.yml` не используется на проде

`README.md:132` предлагает:

```bash
docker compose up -d --build
docker compose logs -f --tail=100 bot
```

А контейнер на проде называется **`bot-wi188f7kradbxpz2efrl7vms`**.
Compose дал бы имя `schedule-bot` (так в `container_name`). Значит
запуск идёт руками:

```bash
docker run -d --name bot-wi188f7kradbxpz2efrl7vms \
  --restart unless-stopped --env-file .env \
  -v /home/virprom/schedule-pipeline/data:/data \
  schedule-bot:latest
```

Расхождение не смертельное, но:

- `docker compose logs` из README **не покажет логи** этого контейнера;
- обновление через `docker compose up -d --build` создаст **второй**
  контейнер рядом, и два процесса начнут писать в одну SQLite.

**Ротация логов при этом работает** — но не благодаря compose. Проверил
`docker inspect`:

```
LogConfig: json-file map[max-file:3 max-size:10m]
```

Настройки приходят из `/etc/docker/daemon.json`, то есть действуют
глобально на все контейнеры сервера:

```json
"log-driver": "json-file",
"log-opts": { "max-file": "3", "max-size": "10m" }
```

Значит строки `logging:` в `docker-compose.yml` дублируют то, что уже
есть на уровне демона. Не вредно, но создаёт впечатление, что без
compose ротация не работает.

Последний пункт — самый неприятный. Стоит либо привести README к
ручному запуску, либо перейти на compose целиком.

## 4. Расхождение `.env.example` и прод-`.env`

`.env.example` (в git):

```
BOT_TOKEN, ADMINS, SQLITE_PATH, SCHEDULE_URL, PHOTOS_PATH, TZ
```

Прод-`.env` (на сервере):

```
BOT_TOKEN, ADMINS, SQLITE_PATH, SCHEDULE_URL, BASE_URL, POLL_INTERVAL, NOTIFY_RATE
```

Два разрыва:

- **`BASE_URL`, `POLL_INTERVAL`, `NOTIFY_RATE` есть только на проде** —
  и ни один не читается кодом (см. план 051). Кто-то добавил их в
  надежде настроить, ничего не изменилось.
- **`PHOTOS_PATH` и `TZ` есть только в example.** На проде работает
  дефолт `/data/photos` — он совпадает с тем, что в example, так что
  незаметно. `TZ` **не читается `config.py` вообще**, но работает:
  проверил контейнер, `date` и `datetime.now()` дают +07, совпадает с
  хостом. Значит `TZ` применяется через libc, а не через конфиг.

## Проверено и признано корректным

**`TZ` действительно работает.** Проверил в контейнере:

```
TZ=Asia/Krasnoyarsk
Mon Oct 26 00:15:00 +07 2026
python: 2026-10-26 00:15:00.068116
host:   Пн 26 окт 2026 00:15:00 +07
```

Время совпадает с хостом до секунды. Хотя `config.py` эту переменную
не читает, Python берёт зону из окружения — этого достаточно.

**`.dockerignore` правильный.** Исключает `.git`, `.env`, `data/`,
`photos`, `*.db`, `__pycache__`. Секретов в образ не попадает.
Проверил: `.env` в списке есть.

**pip кеш отключён** — `--no-cache-dir`, образ не распухает.

**`pull_policy: never` в compose разумен** — образ собирается локально,
тянуть с registry нечего.

**Логирование в compose настроено верно** (`max-size: 10m`,
`max-file: 3`) — жаль, что не применяется.

## Риски

- **Переход на `USER` сломает права на `/data`.** Файл `database.db` уже
  принадлежит root. Нужно либо `chown` на хосте, либо запуск с
  `--user $(id -u):$(id -g)`, либо оставить как есть. Менять на живой
  базе без бэкапа нельзя.
- **Healthcheck с ночным окном** — та же ловушка, что в плане 049.
  Ночью проверка будет ложно падать.
- **Переход на compose создаст новый контейнер** с другим именем и
  потерей истории. Нужен план миграции: остановить ручной, поднять
  compose-овый, проверить, что данные те же.
- **`copy-test.db` и старые бэкапы** занимают место (36 МБ в `data/`,
  из них 32 МБ фото). Не срочно, но стоит убрать `copy-test.db` —
  он не нужен и принадлежит root.
