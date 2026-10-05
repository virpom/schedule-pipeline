import asyncio
import logging
from typing import Union

from aiogram import Bot
from aiogram import exceptions
from aiogram.types import InlineKeyboardMarkup


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
        logging.error("Telegram server says - Bad Request: chat not found")
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


async def broadcast(
        bot: Bot,
        users: list[Union[str, int]],
        text: str,
        disable_notification: bool = False,
        reply_markup: InlineKeyboardMarkup = None,
) -> int:
    count = 0
    try:
        for user_id in users:
            if await send_message(
                    bot, user_id, text, disable_notification, reply_markup
            ):
                count += 1
            await asyncio.sleep(
                0.05
            )  # 20 messages per second (Limit: 30 messages per second)
    finally:
        logging.info(f"{count} messages successful sent.")

    return count


async def send_photo(
        bot: Bot,
        user_id: Union[int, str],
        photo,
        caption: str = "",
) -> bool:
    try:
        await bot.send_photo(user_id, photo, caption=caption)
    except exceptions.TelegramBadRequest:
        logging.error("Telegram server says - Bad Request: chat not found")
    except exceptions.TelegramForbiddenError:
        logging.error(f"Target [ID:{user_id}]: got TelegramForbiddenError")
    except exceptions.TelegramRetryAfter as e:
        logging.error(f"Target [ID:{user_id}]: Flood limit. Sleep {e.retry_after}s")
        await asyncio.sleep(e.retry_after)
        return await send_photo(bot, user_id, photo, caption)
    except exceptions.TelegramAPIError:
        logging.exception(f"Target [ID:{user_id}]: failed")
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
        if photo:
            ok = await send_photo(bot, user_id, photo, text)
        else:
            ok = await send_message(bot, user_id, text)
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
        if await send_message(bot, user_id, text):
            sent += 1
        await asyncio.sleep(delay)
    logging.info("broadcast_many: %d/%d sent at %.1f msg/s", sent, len(items), rate)
    return sent
