"""Один 429 не останавливает всю рассылку.

План 017. `send_message` ловил `TelegramRetryAfter` и спал прямо внутри
себя. Звали его по одному в цикле `broadcast_many`, поэтому сон на
одного адресата держал всех остальных.

Замер на стабе до правки (5 адресатов, delay=0.01, retry_after=2):
адресаты 2–5 ждали, пока отработает сон для первого. После правки все
пять попыток идут за 0.04 с, и уже потом один общий сон на пачку.
"""
import asyncio
import inspect

from aiogram import exceptions

from tgbot.services import broadcaster


class _Bot:
    """Бот, который один раз отдаёт 429 одному адресату."""

    def __init__(self, flood_chat=1, retry_after=0):
        self.flood_chat = flood_chat
        self.retry_after = retry_after
        self.attempts = []
        self.seen = set()

    async def send_message(self, chat_id, text, **kw):
        self.attempts.append(chat_id)
        if chat_id == self.flood_chat and chat_id not in self.seen:
            self.seen.add(chat_id)
            raise exceptions.TelegramRetryAfter(
                method=None, message="flood", retry_after=self.retry_after)


def _items(n=5):
    return [(i, f"msg{i}") for i in range(n)]


def test_retry_after_does_not_sleep_inside_send_message():
    """send_message отдаёт 429 наружу, а не спит сам."""
    src = inspect.getsource(broadcaster.send_message)
    assert "asyncio.sleep(e.retry_after)" not in src, "сон внутри отправки"
    assert "retry_after[0] = max(" in src, "retry_after не передаётся наружу"


def test_send_message_accepts_retry_after():
    sig = inspect.signature(broadcaster.send_message)
    assert "retry_after" in sig.parameters


def test_send_message_returns_false_on_429():
    wait = [0.0]
    ok = asyncio.run(broadcaster.send_message(
        _Bot(retry_after=7), 1, "hi", retry_after=wait))
    assert ok is False, "429 не считается провалом"
    assert wait[0] == 7, "retry_after не дошёл до вызывающего"


def test_queue_not_blocked_by_one_429():
    """Главное: остальные получают сообщения, не дожидаясь сна."""
    broadcaster._retry["max"] = 0.0
    bot = _Bot(retry_after=1)
    asyncio.run(broadcaster.broadcast_many(bot, _items(5), rate=100))
    # первый проход: все пять попыток, потом один повтор адресата 1
    first_pass = bot.attempts[:5]
    assert first_pass == [0, 1, 2, 3, 4], f"цикл прервался: {first_pass}"


def test_all_recipients_eventually_delivered():
    broadcaster._retry["max"] = 0.0
    bot = _Bot(retry_after=0)
    sent = asyncio.run(broadcaster.broadcast_many(bot, _items(5), rate=100))
    assert sent == 5, "сообщение потерялось после 429"


def test_single_sleep_for_whole_batch():
    """Спим один раз за пачку, а не на каждого неудачника."""
    broadcaster._retry["max"] = 0.0

    class _TwoFails(_Bot):
        async def send_message(self, chat_id, text, **kw):
            if chat_id in (1, 2) and chat_id not in self.seen:
                self.seen.add(chat_id)
                self.attempts.append(chat_id)
                raise exceptions.TelegramRetryAfter(
                    method=None, message="flood", retry_after=0)
            return await super().send_message(chat_id, text, **kw)

    slept = []
    real = asyncio.sleep

    async def fake_sleep(sec):
        # считаем только длинные сны (общий), паузы delay пропускаем
        if sec > 0.1:
            slept.append(sec)
        await real(0)

    src_call = broadcaster.asyncio
    orig = src_call.sleep
    src_call.sleep = fake_sleep
    try:
        asyncio.run(broadcaster.broadcast_many(_TwoFails(retry_after=0), _items(4), rate=100))
    finally:
        src_call.sleep = orig
    assert len(slept) >= 1, "нет общего сна"
    assert sum(slept) == broadcaster._DEFAULT_RETRY_WAIT, f"снов несколько: {slept}"


def test_default_wait_when_no_retry_after():
    broadcaster._retry["max"] = 0.0
    assert broadcaster._take_retry() == broadcaster._DEFAULT_RETRY_WAIT


def test_take_retry_resets():
    broadcaster._retry["max"] = 0.0
    broadcaster._stash_retry(12)
    assert broadcaster._take_retry() == 12
    assert broadcaster._take_retry() == broadcaster._DEFAULT_RETRY_WAIT


def test_stash_keeps_max():
    broadcaster._retry["max"] = 0.0
    broadcaster._stash_retry(3)
    broadcaster._stash_retry(9)
    broadcaster._stash_retry(1)
    assert broadcaster._retry["max"] == 9
    broadcaster._retry["max"] = 0.0


def test_broadcast_reports_failures():
    src = inspect.getsource(broadcaster.broadcast_many)
    assert "не доставлено" in src, "провалы не логируются"


def test_broadcast_schedule_not_blocked_either():
    """Основная рассылка расписания тоже не стоит на одном 429."""
    broadcaster._retry["max"] = 0.0
    bot = _Bot(retry_after=0)
    items = [(i, f"msg{i}", None) for i in range(5)]
    sent = asyncio.run(broadcaster.broadcast_schedule(bot, items, rate=100))
    assert bot.attempts[:5] == [0, 1, 2, 3, 4], f"цикл прервался: {bot.attempts}"
    assert sent == 5


def test_send_photo_does_not_sleep():
    src = inspect.getsource(broadcaster.send_photo)
    assert "asyncio.sleep(e.retry_after)" not in src, "сон внутри отправки фото"
