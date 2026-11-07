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

# У вуза свой источник (norvuz.ru) и свой файл. Когда лежит сайт колледжа,
# расписание вуза при этом может быть свежим — и наоборот. Один общий
# флаг врал: студент вуза видел «сайт колледжа не отвечает».
LAST_OK_VUZ = "last_sync_ok_vuz"

# Сколько ждём, прежде чем считать данные устаревшими. Зашитый порог
# расходился с настройкой: `/setpoll 3600` давал интервал 60 минут при
# пороге 30, и между опросами экран почти всегда показывал «данные
# устарели» — предупреждение, которое быстро привыкают игнорировать.
# Теперь порог считается от интервала (три опроса, не меньше 30 минут).
STALE_AFTER = datetime.timedelta(minutes=30)


async def stale_after(repo: RequestsRepo) -> datetime.timedelta:
    """Порог устаревания: три интервала опроса, но не меньше 30 минут."""
    raw = (await repo.settings.get_all()).get("poll_interval")
    try:
        interval = int(raw) if raw else 300
    except (TypeError, ValueError):
        interval = 300
    return datetime.timedelta(seconds=max(interval * 3, int(STALE_AFTER.total_seconds())))


async def mark_ok(repo: RequestsRepo) -> None:
    await repo.settings.set(LAST_OK, datetime.datetime.now().isoformat(timespec="seconds"))


async def mark_ok_vuz(repo: RequestsRepo) -> None:
    await repo.settings.set(LAST_OK_VUZ,
                            datetime.datetime.now().isoformat(timespec="seconds"))


async def last_ok_vuz(repo: RequestsRepo) -> datetime.datetime | None:
    raw = await repo.settings.get(LAST_OK_VUZ)
    if not raw:
        return None
    try:
        return datetime.datetime.fromisoformat(raw)
    except ValueError:
        return None


async def is_stale_vuz(repo: RequestsRepo) -> bool:
    when = await last_ok_vuz(repo)
    if when is None:
        return True
    settings = await repo.settings.get_all()
    return datetime.datetime.now() - when > await _grace(repo, settings)


async def last_ok(repo: RequestsRepo) -> datetime.datetime | None:
    raw = await repo.settings.get(LAST_OK)
    if not raw:
        return None
    try:
        return datetime.datetime.fromisoformat(raw)
    except ValueError:
        return None


def in_night(now: datetime.datetime, start_str: str, end_str: str) -> bool:
    """Попадает ли момент в ночное окно, когда поллер намеренно спит.

    Вынесено из поллера: порог устаревания должен знать то же самое
    окно, иначе ночью он объявляет сбой там, где его нет.
    """
    if not start_str or not end_str:
        return False
    try:
        start = datetime.time.fromisoformat(start_str)
        end = datetime.time.fromisoformat(end_str)
    except ValueError:
        return False
    # Кривое значение могло попасть в БД до того, как /setnight начал
    # отбивать часы с поясом. Сравнение aware с naive — TypeError,
    # который поллер ловит общим except и молча перестаёт опрашивать.
    if start.tzinfo is not None or end.tzinfo is not None:
        return False
    if start == end:
        return False
    t = now.time()
    if start < end:
        return start <= t < end
    return t >= start or t < end


def _night_length(settings: dict) -> datetime.timedelta:
    """Длительность ночного окна. Кривое значение — ноль."""
    try:
        start = datetime.time.fromisoformat(settings["night_start"])
        end = datetime.time.fromisoformat(settings["night_end"])
    except (KeyError, TypeError, ValueError):
        return datetime.timedelta()
    if start == end:
        return datetime.timedelta()
    today = datetime.date.today()
    delta = (datetime.datetime.combine(today, end)
             - datetime.datetime.combine(today, start))
    if delta < datetime.timedelta():
        delta += datetime.timedelta(days=1)
    return delta


async def _grace(repo: RequestsRepo, settings: dict) -> datetime.timedelta:
    """Порог с поправкой на ночь: пока поллер спит, данные не стареют.

    Без поправки предупреждение «сайт не отвечает» висело с 23:27 до
    07:05 — треть суток каждую ночь, хотя сайт жив. Порог на это время
    растягивается на длину ночного окна.
    """
    grace = await stale_after(repo)
    if in_night(datetime.datetime.now(),
                settings.get("night_start"), settings.get("night_end")):
        grace += _night_length(settings)
    return grace


async def is_stale(repo: RequestsRepo) -> bool:
    """Данные с сайта не обновлялись дольше порога.

    ``None`` (ни одного успешного прохода) тоже считается устаревшим:
    мы не знаем, что там на сайте, и честнее об этом сказать.
    """
    when = await last_ok(repo)
    if when is None:
        return True
    settings = await repo.settings.get_all()
    return datetime.datetime.now() - when > await _grace(repo, settings)
