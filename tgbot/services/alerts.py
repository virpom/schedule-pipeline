"""Тревоги для админа: что-то сломалось, и бот не может это исправить сам.

Зачем отдельный модуль: поллер ловит исключения и пишет их в лог. Лог
читают, когда уже сломано. Админ должен узнать раньше — до того, как
студенты начнут жаловаться, что расписание не обновилось.

Тревога не повторяется каждый цикл: помним, о чём уже сообщили, и молчим,
пока проблема та же. Когда отпустило — пишем «восстановилось», чтобы
не гадать, само прошло или нет.
"""
import hashlib
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from config import Config
from infrastructure.database.repo.requests import RequestsRepo

log = logging.getLogger(__name__)

# Ключи в таблице setting. Храним хеш последнего отправленного текста:
# пока он не меняется, повторно не шлём. Хеш, а не текст, потому что
# value в setting — String(128), а текст тревоги бывает длиннее.
ALERT_KEY = "alert_{kind}"


async def alert(bot: Bot, repo: RequestsRepo, config: Config, kind: str, text: str) -> None:
    """Сообщить админам о проблеме. Повтор с тем же текстом не отправляется.

    ``kind`` — короткий ключ проблемы (``structure``, ``site``), чтобы
    разные проблемы не глушили друг друга.
    """
    key = ALERT_KEY.format(kind=kind)
    digest = hashlib.sha256(text.encode()).hexdigest()
    if await repo.settings.get(key) == digest:
        return  # об этом уже сообщили, не спамим

    await repo.settings.set(key, digest)
    await _send(bot, config, f"⚠️ <b>Проблема с расписанием</b>\n\n{text}")
    log.warning("тревога админу (%s): %s", kind, text)


async def clear(bot: Bot, repo: RequestsRepo, config: Config, kind: str, text: str) -> None:
    """Сообщить, что проблема ушла. Только если о ней раньше сообщали."""
    key = ALERT_KEY.format(kind=kind)
    if not await repo.settings.get(key):
        return  # тревоги не было — нечего и закрывать

    await repo.settings.set(key, "")
    await _send(bot, config, f"✅ <b>Восстановилось</b>\n\n{text}")
    log.info("тревога снята (%s)", kind)


async def _send(bot: Bot, config: Config, text: str) -> None:
    for admin_id in config.tg_bot.admin_ids:
        try:
            await bot.send_message(admin_id, text)
        except TelegramAPIError as e:
            # Админ мог заблокировать бота — это не повод ронять поллер.
            log.warning("не удалось отправить тревогу %s: %s", admin_id, e)
