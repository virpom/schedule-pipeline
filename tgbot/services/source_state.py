"""Состояние источника расписания: когда последний раз всё получилось.

Раньше здесь был один флаг ``site_down``, и он врал в двух местах:

* при частичном сбое (упали замены, но не очное) ставился «сайт лежит»,
  хотя сайт жив;
* при живом сайте флаг ничего не говорил о том, насколько данные свежие.

Теперь храним факт: время последней успешной синхронизации. Из него
выводится и «сайт недоступен», и «данные устарели».
"""
import datetime

from infrastructure.database.repo.requests import RequestsRepo

# Ключ в таблице setting: ISO-время последнего успешного прохода.
LAST_OK = "last_sync_ok"

# Сколько ждём, прежде чем считать данные устаревшими. Три интервала опроса
# по умолчанию (300 с) — запас на разовый сбой сети, но не на сутки.
STALE_AFTER = datetime.timedelta(minutes=30)


async def mark_ok(repo: RequestsRepo) -> None:
    await repo.settings.set(LAST_OK, datetime.datetime.now().isoformat(timespec="seconds"))


async def last_ok(repo: RequestsRepo) -> datetime.datetime | None:
    raw = await repo.settings.get(LAST_OK)
    if not raw:
        return None
    try:
        return datetime.datetime.fromisoformat(raw)
    except ValueError:
        return None


async def is_stale(repo: RequestsRepo) -> bool:
    """Данные с сайта не обновлялись дольше порога.

    ``None`` (ни одного успешного прохода) тоже считается устаревшим:
    мы не знаем, что там на сайте, и честнее об этом сказать.
    """
    when = await last_ok(repo)
    if when is None:
        return True
    return datetime.datetime.now() - when > STALE_AFTER
