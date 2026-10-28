import asyncio
import datetime
import logging

from aiogram import Bot, exceptions

# Bot API удаляет ~30 сообщений в секунду на бота. Берём 25, а 429
# обрабатываем как в отправке: ждём retry_after и повторяем, иначе на
# пачке в 3000 сообщений половина удалений отвалилась бы.
REVOKE_RATE = 25.0
_DEFAULT_RETRY_WAIT = 5.0
_MAX_RETRIES = 3


async def revoke(bot: Bot, rows: list[tuple[int, int]],
                 rate: float = REVOKE_RATE) -> tuple[int, int]:
    """Удалить ранее отправленные сообщения. Возвращает ``(удалено, не вышло)``.

    Ошибка на одном не рвёт пачку: сообщение могло быть уже удалено
    руками, а старше 48 часов Bot API не удаляет вовсе — это не повод
    оставить остальные.
    """
    delay = 1.0 / max(rate, 0.1)
    removed = failed = 0
    for chat_id, message_id in rows:
        for attempt in range(_MAX_RETRIES + 1):
            try:
                await bot.delete_message(chat_id, message_id)
            except exceptions.TelegramRetryAfter as e:
                if attempt == _MAX_RETRIES:
                    failed += 1
                    break
                await asyncio.sleep(e.retry_after or _DEFAULT_RETRY_WAIT)
                continue
            except Exception as e:
                # TelegramBadRequest («message can't be deleted»),
                # TelegramForbiddenError и сетевые — всё это «не вышло,
                # идём дальше», а не «останови отзыв».
                logging.warning("revoke: %s:%s не удалено: %s",
                                chat_id, message_id, e)
                failed += 1
            else:
                removed += 1
            break
        await asyncio.sleep(delay)
    logging.info("revoke: удалено %d из %d", removed, len(rows))
    return removed, failed


def describe(moment: datetime.datetime | None, count: int) -> str:
    """Строка подтверждения: что и когда было отправлено."""
    if moment is None or not count:
        return ""
    return f"{count} сообщений за {moment:%d.%m %H:%M}"
