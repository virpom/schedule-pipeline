# Развёртывание

Бот — один контейнер с Python-процессом внутри. Внешних сервисов нет:
ни Postgres, ни Redis, ни отдельного воркера.

## Что нужно

- Docker (или Docker Compose)
- Токен бота от [@BotFather](https://t.me/BotFather)
- Свой Telegram ID в `ADMINS`, иначе админка будет недоступна
  (узнать: [@userinfobot](https://t.me/userinfobot))

## Быстрый старт

```bash
git clone <repo> schedule-pipeline && cd schedule-pipeline
cp .env.example .env
$EDITOR .env          # BOT_TOKEN и ADMINS обязательны
docker compose up -d --build
docker compose logs -f --tail=100 bot
```

В логах должны появиться:

```
poller started
bell loop started
```

Значит обе фоновые задачи поднялись. Бот отвечает на `/start`.

## Переменные окружения

Читаются в `config.py` при старте. `.env` подхватывается вручную через
`os.environ.setdefault` — **уже заданные переменные окружения не
перетираются**, поэтому в Docker значения приходят штатно через `env_file`.

| Переменная | Обязательна | По умолчанию | Что это |
|---|---|---|---|
| `BOT_TOKEN` | да | — | токен от BotFather |
| `ADMINS` | нет | пусто | Telegram ID админов через запятую или пробел |
| `SQLITE_PATH` | нет | `database.db` | путь к файлу базы |
| `SCHEDULE_URL` | нет | `https://eios.norvuz.ru/mod/page/view.php?id=49960` | страница-каталог ЭИОС |
| `PHOTOS_PATH` | нет | `/data/photos` | папка с подпапками `monday`…`sunday` |
| `TZ` | нет | — | часовой пояс контейнера |

**Чего в `.env` нет и почему.** Интервал опроса, скорость рассылки, ночная
пауза, дедлайн «занятий нет» и ссылка поддержки живут в таблице `setting`.
Их меняет админ прямо из бота, и они переживают рестарт. Дублировать их в
`.env` значило бы иметь два источника истины, которые разъезжаются.
Значения по умолчанию — в `infrastructure/database/repo/setting.py`.

**`TZ` важна.** От локального времени зависят ночная пауза, дедлайн и
время напоминаний о звонках. Для Норильска — `Asia/Krasnoyarsk` (UTC+7).

## Тома

Один том, одна папка:

```
data/
├── database.db          # SQLite, создаётся при первом старте
└── photos/
    ├── monday/          # картинки для понедельника
    ├── tuesday/
    ├── wednesday/
    ├── thursday/
    ├── friday/
    ├── saturday/
    └── sunday/
```

В контейнере это `/data`, на хосте — `./data` рядом с `docker-compose.yml`.

**Резервная копия** — это просто копия `data/`. Остановите контейнер,
скопируйте папку, запустите снова:

```bash
docker compose stop bot
tar czf backup-$(date +%F).tar.gz data/
docker compose start bot
```

SQLite в режиме WAL переживает и копирование на живой базе, но
останавливать контейнер надёжнее.

## Миграции

Накатываются автоматически при старте (`infrastructure/database/migrations_runner.py`
вызывает alembic). Руками делать ничего не нужно.

Существующие миграции:

| Ревизия | Что делает |
|---|---|
| `0001_baseline` | базовая схема |
| `0002_editors` | таблицы редакторов и журнала правок |

Если в логах видно `alembic.runtime.migration` — это норма, миграции идут.
Ошибка миграции останавливает старт: бот не поднимется на несовместимой схеме.

## Обновление

```bash
git pull origin master
docker compose up -d --build
docker compose logs -f --tail=50 bot
```

Пересборка занимает около минуты. Данные не теряются: они в `./data`,
а не в образе.

Если обновились зависимости (`requirements.txt`), пересборка обязательна —
`--build` её и делает.

## Проверка, что всё живо

```bash
# контейнер запущен и не перезапускается
docker compose ps

# ошибки за последнее время (должно быть пусто)
docker compose logs --since 10m bot | grep -iE 'error|traceback'

# бот отвечает Telegram
docker compose exec bot python -c "
import os, json, urllib.request
t = os.environ['BOT_TOKEN']
r = json.load(urllib.request.urlopen(f'https://api.telegram.org/bot{t}/getMe'))
print(r['result']['username'])
"
```

В самом боте: `/stats` показывает пользователей, объём расписания и
**состояние источника**:

```
✅ ЭИОС: 24.10 01:50
```

или, если сайт не отвечает:

```
⚠️ ЭИОС не отвечает (успех: 24.10 01:50)
```

## Прод (как развёрнуто сейчас)

Контейнер запускается напрямую через `docker run`, без compose:

```bash
docker run -d \
  --name bot-wi188f7kradbxpz2efrl7vms \
  --restart unless-stopped \
  --env-file .env \
  -v /home/virprom/schedule-pipeline/data:/data \
  schedule-bot:latest
```

Код — `/opt/projects/schedule-pipeline`, база — `/home/virprom/schedule-pipeline/data/database.db`.

Обновление:

```bash
cd /opt/projects/schedule-pipeline
git pull origin master
docker build -q -t schedule-bot:latest .
docker rm -f bot-wi188f7kradbxpz2efrl7vms
docker run -d --name bot-wi188f7kradbxpz2efrl7vms \
  --restart unless-stopped --env-file .env \
  -v /home/virprom/schedule-pipeline/data:/data schedule-bot:latest
```

## Секреты

`.env` содержит токен бота и **не должен попадать в git**. Он в
`.gitignore` и `.dockerignore`.

Права на файл:

```bash
chmod 600 .env
```

Если токен утёк — перевыпустить у BotFather (`/revoke`), обновить `.env`,
перезапустить контейнер. Старый токен перестанет работать сразу.

## Часовой пояс

Контейнер по умолчанию живёт в UTC. Если забыть `TZ`, ночная пауза
и дедлайн сработают не тогда, когда ожидается — например, «дедлайн 20:00»
наступит в 3 часа ночи по Норильску.

Проверить время внутри контейнера:

```bash
docker compose exec bot date
```
