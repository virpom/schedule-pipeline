# План 127: 30 команд `docker compose` в документации не работают

> **СДЕЛАНО 27.10.2026** (коммиты `9df8ea4`, `d1edbf8`).
>
> Нашёл 31 команду, не 30: `docs/TROUBLESHOOTING.md` — 17,
> `docs/DEPLOYMENT.md` — 10, `README.md` — 2, `docs/PARSING.md` — 1.
> Все заменены на рабочие `docker ...` с реальным именем прод-контейнера
> `bot-wi188f7kradbxpz2efrl7vms`.
>
> Три упоминания `docker compose` оставлены намеренно — это
> предупреждения «так делать нельзя»: `docker compose up` создал бы
> второй контейнер на том же токене.
>
> Docker на машине, где правилось, не установлен, поэтому команды
> сверены с `Dockerfile` и разделом «Прод», а не запуском. Имя
> контейнера теперь в двух местах (`TROUBLESHOOTING.md:6` и
> `DEPLOYMENT.md`) — при пересоздании с другим `--name` править оба.

**Приоритет:** высокий для эксплуатации. Это не «документация устарела»
— это инструкция, которая **молча не делает ничего** и возвращает
код успеха.

**Трудоёмкость:** S (правка текста, ~30 строк).

## Что происходит

В репозитории есть `docker-compose.yml`:

```yaml
services:
  bot:
    image: schedule-bot:latest
    container_name: schedule-bot
    ...
```

Документация на него опирается — **30 команд**:

```
docs/TROUBLESHOOTING.md:  17
docs/DEPLOYMENT.md:       10
README.md:                 2
docs/PARSING.md:           1
```

Но на проде контейнер запущен **не через compose**, а через `docker run`:

```
docker ps:  bot-wi188f7kradbxpz2efrl7vms   Up 10 hours
```

Имя `schedule-bot` (которое задаёт compose) не существует. Значит
compose видит пустой проект.

## Что это даёт — проверил на проде

```
$ cd /opt/projects/schedule-pipeline && docker compose ps
NAME      IMAGE     COMMAND   SERVICE   CREATED   STATUS   PORTS
                                                    <- пусто, exit=0

$ docker compose logs --tail=2 bot
                                                    <- пусто, exit=0

$ docker compose stop bot
                                                    <- ничего, exit=0

$ docker ps --filter name=bot-wi188f7kradbxpz2efrl7vms
bot-wi188f7kradbxpz2efrl7vms   Up 10 hours            <- БОТ ЖИВ
```

**`docker compose stop bot` вернул код 0 и не остановил бота.** Админ,
следующий инструкции `DEPLOYMENT.md:79`, будет уверен, что сервис
остановлен. Он не остановлен.

## Почему это опаснее обычной устаревшей документации

Обычная ошибка в инструкции даёт **сообщение об ошибке** — админ
поймёт и пойдёт искать. Здесь всё наоборот:

| Команда | Что ждёт админ | Что происходит |
|---|---|---|
| `compose ps` | список контейнеров | пустая таблица, код 0 |
| `compose logs -f bot` | поток логов | пусто, код 0 |
| `compose stop bot` | бот остановлен | бот работает, код 0 |
| `compose up -d --build` | деплой | создаст **второй** контейнер `schedule-bot` |

Последнее — худший сценарий. `docker compose up -d` создаст
**второй экземпляр бота с тем же токеном**. Два процесса на одном
токене дерутся за `getUpdates`, и бот начинает отвечать через раз.
Ровно об этом предупреждает `TROUBLESHOOTING.md:44`:

```
**Проверить, что нет второго экземпляра.** Два процесса с одним токеном
дерутся за обновления, и бот отвечает через раз.
```

Документ предупреждает об опасности и сам же к ней ведёт.

## Что сделать

**Вариант А (предпочтительный) — перейти на compose.** Привести
`docker-compose.yml` в соответствие с фактическим запуском: убрать
`container_name` (или задать текущее имя), добавить `logging` как в
`docker run`. Затем один раз пересоздать контейнер через compose. После
этого все 30 команд заработают.

**Вариант Б — переписать документацию под `docker run`.** 30 команд
заменить на реальные:

```bash
docker logs -f --tail=100 bot-wi188f7kradbxpz2efrl7vms
docker ps --filter name=bot-wi188f7kradbxpz2efrl7vms
```

Минус: длинное имя контейнера в каждой команде.

**Вариант В (самый дешёвый) — задать короткое имя.** Пересоздать
контейнер с `--name schedule-bot`, тогда документация станет верной
без правки текста. Но `container_name` в compose всё равно конфликтует
с существующим `bot-wi188f7kradbxpz2efrl7vms` — его надо удалить.

**Что рекомендую:** вариант А. `docker-compose.yml` уже написан
правильно, кроме `container_name`. Это одна строка правки против
тридцати.

## Как проверить после исправления

```bash
cd /opt/projects/schedule-pipeline
docker compose ps                 # должен показать ОДИН контейнер Up
docker compose logs --tail=5 bot  # должен показать реальные логи
docker ps --format '{{.Names}}' | grep -c bot   # должно быть 1, не 2
```

Последняя проверка — ключевая: после `compose up` не должно появиться
второго контейнера.

## Проверил и признал корректным

**`docker-compose.yml` сам по себе написан верно:** `pull_policy: never`
(образ собирается локально), `restart: unless-stopped`, том `./data:/data`,
`env_file: .env`, ротация логов `10m × 3`. Всё как надо.

**Команда проверки токена в `TROUBLESHOOTING.md:31`** рабочая по смыслу,
но тоже требует `compose exec bot`, а не `docker exec`.

**Предупреждение о двух экземплярах** (`TROUBLESHOOTING.md:44`) —
правильное и важное. Просто команда рядом с ним не работает.

## Риски

- **Переход на compose пересоздаст контейнер.** Это простой на время
  деплоя (~40 с) и смена имени. Данные в `/home/virprom/schedule-pipeline/data`
  не тронутся — том монтируется по пути.
- **Если ошибиться с `container_name`,** `compose up` создаст второй
  контейнер рядом с работающим. Проверять `docker ps` до и после.
- **Проверил гипотезу про Coolify — она неверна.** `docs/ROADMAP.md:8`
  упоминает деплой через Coolify API, и Coolify на сервере действительноесть:

  ```
  coolify, coolify-db, coolify-redis, coolify-sentinel, coolify-proxy
  ```

  Но наш контейнер им **не управляется** — у него пустые labels:

  ```
  docker inspect ... --format '{{json .Config.Labels}}'  ->  {}
  ```

  и параметры ровно те, что даёт ручной `docker run`:

  ```
  restart:   unless-stopped
  создан:    2026-10-26T04:51:20
  команда:   python [main.py]
  монтирует: /home/virprom/schedule-pipeline/data -> /data
  ```

  Coolify ставит свои labels и своё имя. Значит это ручной запуск, и
  `docker-compose.yml` — действительно мёртвый артефакт. Вывод не
  меняется: документацию надо привести к тому, как сервис запущен
  на самом деле.
