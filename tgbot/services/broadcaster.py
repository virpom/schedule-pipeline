import asyncio
import logging
from typing import Union

from aiogram import Bot
from aiogram import exceptions
from aiogram.types import FSInputFile, InlineKeyboardMarkup

# file_id, который Telegram вернул после первой загрузки файла. Повторная
# отправка по нему не требует читать файл с диска и загружать его заново:
# 196 загрузок по 390 КБ превращаются в одну.
# Живёт в памяти процесса: после рестарта каждый файл загрузится один раз.
_file_ids: dict[str, str] = {}


async def send_message(
        bot: Bot,
        user_id: Union[int, str],
        text: str,
        disable_notification: bool = False,
        reply_markup: InlineKeyboardMarkup = None,
) -> bool:
    try:
        await bot.send_message(
            user_id,
            text,
            disable_notification=disable_notification,
            reply_markup=reply_markup,
        )
    except exceptions.TelegramBadRequest as e:
        logging.error("Target [ID:%s] BadRequest: %s", user_id, e.message)
    except exceptions.TelegramForbiddenError:
        logging.error(f"Target [ID:{user_id}]: got TelegramForbiddenError")
    except exceptions.TelegramRetryAfter as e:
        logging.error(
            f"Target [ID:{user_id}]: Flood limit is exceeded. Sleep {e.retry_after} seconds."
        )
        await asyncio.sleep(e.retry_after)
        return await send_message(
            bot, user_id, text, disable_notification, reply_markup
        )  # Recursive call
    except exceptions.TelegramAPIError:
        logging.exception(f"Target [ID:{user_id}]: failed")
    else:
        logging.info(f"Target [ID:{user_id}]: success")
        return True
    return False


async def _send_photo_by_id(bot: Bot, user_id, photo, caption: str):
    """Отправить фото по кэшу file_id, загрузив его только в первый раз."""
    key = str(photo)
    cached = _file_ids.get(key)
    if cached:
        try:
            await bot.send_photo(user_id, cached, caption=caption)
            return
        except exceptions.TelegramBadRequest as e:
            # file_id привязан к боту и может протухнуть: Telegram чистит
            # старые файлы. Без повтора один битый id сломал бы отправку
            # этому человеку навсегда.
            logging.warning("file_id протух для %s (%s), грузим заново", key, e.message)
            _file_ids.pop(key, None)
    msg = await bot.send_photo(user_id, FSInputFile(photo), caption=caption)
    if msg and getattr(msg, "photo", None):
        _file_ids[key] = msg.photo[-1].file_id


async def send_photo(
        bot: Bot,
        user_id: Union[int, str],
        photo,
        caption: str = "",
) -> bool:
    try:
        await _send_photo_by_id(bot, user_id, photo, caption)
    except exceptions.TelegramBadRequest as e:
        logging.error("Target [ID:%s] BadRequest: %s", user_id, e.message)
    except exceptions.TelegramForbiddenError:
        logging.error(f"Target [ID:{user_id}]: got TelegramForbiddenError")
    except exceptions.TelegramRetryAfter as e:
        logging.error(f"Target [ID:{user_id}]: Flood limit. Sleep {e.retry_after}s")
        await asyncio.sleep(e.retry_after)
        return await send_photo(bot, user_id, photo, caption)
    except exceptions.TelegramAPIError:
        logging.exception(f"Target [ID:{user_id}]: failed")
    except OSError as e:
        # FSInputFile читает файл лениво — FileNotFoundError и
        # PermissionError вылетают уже внутри send_photo, а они не
        # подклассы TelegramAPIError: без этой ветки исключение уходило
        # наружу и роняло всю рассылку, а не одного получателя.
        logging.error("Target [ID:%s]: файл фото недоступен: %s (%s)",
                      user_id, photo, e)
    else:
        return True
    return False


async def broadcast_schedule(
        bot: Bot,
        items: list[tuple[Union[str, int], str, Union[str, None]]],
        rate: float = 20.0,
) -> int:
    """Send schedule messages (text or photo+text) with rate limiting."""
    if not items:
        return 0
    delay = 1.0 / max(rate, 0.1)
    sent = 0
    for user_id, text, photo in items:
        # Второй уровень защиты: даже неожиданное исключение на одном
        # получателе не должно лишать расписания остальных.
        try:
            if photo:
                ok = await send_photo(bot, user_id, photo, text)
            else:
                ok = await send_message(bot, user_id, text)
        except Exception:
            logging.exception("broadcast: сбой на %s, продолжаем", user_id)
            ok = False
        if ok:
            sent += 1
        await asyncio.sleep(delay)
    logging.info("broadcast_schedule: %d/%d sent at %.1f msg/s", sent, len(items), rate)
    return sent


async def broadcast_many(
        bot: Bot,
        items: list[tuple[Union[str, int], str]],
        rate: float = 5.0,
) -> int:
    """Send personalized messages with rate limiting.

    Telegram limits are ~30 msg/s globally per bot, plus per-chat flood
    control (429 retry_after). Here we pace at `rate` msg/s and let
    send_message() handle retry_after / failures, so a slow or blocked
    recipient never stalls the rest of the queue.
    """
    if not items:
        return 0
    delay = 1.0 / max(rate, 0.1)
    sent = 0
    for user_id, text in items:
        try:
            if await send_message(bot, user_id, text):
                sent += 1
        except Exception:
            logging.exception("broadcast: сбой на %s, продолжаем", user_id)
        await asyncio.sleep(delay)
    logging.info("broadcast_many: %d/%d sent at %.1f msg/s", sent, len(items), rate)
    return sent
