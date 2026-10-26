"""Логика «сайт недоступен»: что показать, когда данных нет.

Главное правило: постоянное расписание верно всегда, поэтому его не
скрываем. Замены могут отсутствовать и на живом сайте — это норма, а не
сбой. Предупреждаем только тогда, когда сайт реально не отвечает.
"""
import datetime

from common.schedule import (format_no_lessons, format_not_published,
                             format_stale_warning, format_unverified)

D = datetime.date(2026, 10, 27)
LAST_OK = datetime.datetime(2026, 10, 24, 9, 30)


def test_warning_says_when_site_went_down():
    text = format_stale_warning(LAST_OK)
    assert "24.10 09:30" in text
    assert "Замены" in text


def test_warning_without_any_successful_sync():
    text = format_stale_warning(None)
    assert "ни разу" in text


def test_no_lessons_has_no_warning_when_fresh():
    """Сайт жив, пар нет — обычный ответ, предупреждать не о чем."""
    text = format_no_lessons(D)
    assert "Занятий нет" in text
    assert "⚠️" not in text


def test_unverified_does_not_claim_there_are_no_lessons():
    """Без связи с сайтом нельзя утверждать, что пар нет."""
    text = format_unverified(D, LAST_OK)
    assert "не отвечает" in text
    assert "Занятий нет 🙌" not in text


def test_unverified_mentions_base_schedule():
    """Постоянное расписание всё-таки известно — так и говорим."""
    text = format_unverified(D, LAST_OK)
    assert "постоянному расписанию" in text


def test_not_published_differs_from_unverified():
    """«Ещё не выложено» и «не смогли проверить» — разные вещи."""
    fresh = format_not_published(D)
    stale = format_unverified(D, LAST_OK)
    assert fresh != stale
    assert "не выложено" in fresh
    assert "не выложено" not in stale


def test_warning_appended_not_replacing_schedule():
    """Предупреждение дописывается к расписанию, а не затирает его."""
    base = "📅 Среда\n\n1) 09:00  Математика"
    full = base + format_stale_warning(LAST_OK)
    assert full.startswith(base)
    assert "не отвечает" in full


def test_stale_threshold():
    """Порог: свежие данные — не предупреждаем, старые — предупреждаем."""
    import asyncio
    from tgbot.services import source_state

    class FakeSettings:
        def __init__(self, raw): self.raw = raw
        async def get(self, key): return self.raw
        async def get_all(self): return {"poll_interval": "300"}

    class FakeRepo:
        def __init__(self, raw): self.settings = FakeSettings(raw)

    now = datetime.datetime.now()

    fresh = FakeRepo((now - datetime.timedelta(minutes=5)).isoformat())
    assert asyncio.run(source_state.is_stale(fresh)) is False

    old = FakeRepo((now - datetime.timedelta(hours=5)).isoformat())
    assert asyncio.run(source_state.is_stale(old)) is True

    never = FakeRepo(None)
    assert asyncio.run(source_state.is_stale(never)) is True, \
        "без единого успешного прохода честнее предупредить"

    broken = FakeRepo("не дата")
    assert asyncio.run(source_state.is_stale(broken)) is True


def test_stale_threshold_follows_poll_interval():
    """Порог устаревания не должен отставать от интервала опроса.

    При /setpoll 3600 интервал 60 минут, а порог был зашит в 30 —
    значит между опросами экран почти всегда показывал «данные
    устарели». Предупреждение, которое горит постоянно, перестают
    читать.
    """
    import asyncio
    from tgbot.services import source_state

    class FakeSettings:
        def __init__(self, interval): self.interval = interval
        async def get(self, key): return None
        async def get_all(self): return {"poll_interval": str(self.interval)}

    class FakeRepo:
        def __init__(self, interval): self.settings = FakeSettings(interval)

    async def threshold(interval):
        return await source_state.stale_after(FakeRepo(interval))

    # Дефолт: три интервала по 300 с = 15 мин, но не меньше 30.
    assert asyncio.run(threshold(300)) == datetime.timedelta(minutes=30)
    # Интервал вырос — порог вырос вместе с ним.
    assert asyncio.run(threshold(3600)) == datetime.timedelta(minutes=180)
    assert asyncio.run(threshold(1800)) == datetime.timedelta(minutes=90)


def test_stale_after_survives_broken_setting():
    """Мусор в настройке не должен ронять экран."""
    import asyncio
    from tgbot.services import source_state

    class FakeSettings:
        async def get(self, key): return None
        async def get_all(self): return {"poll_interval": "не число"}

    class FakeRepo:
        settings = FakeSettings()

    assert asyncio.run(source_state.stale_after(FakeRepo())) == \
        datetime.timedelta(minutes=30)
