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

# Сколько ждать повтор, если 429 пришёл без внятного retry_after.
_DEFAULT_RETRY_WAIT = 5.0


# Максимальный retry_after, накопленный за проход цикла. Сон ставим
# один раз на всю пачку: 429 от одного адресата значит, что лимитит бот
# целиком, и ждать надо всем.
_retry = {"max": 0.0}


def _stash_retry(seconds: float) -> None:
    if seconds > _retry["max"]:
        _retry["max"] = seconds


def _take_retry() -> float:
    wait = _retry["max"] or _DEFAULT_RETRY_WAIT
    _retry["max"] = 0.0
    return wait


async def send_message(
        bot: Bot,
        user_id: Union[int, str],
        text: str,
        disable_notification: bool = False,
        reply_markup: InlineKeyboardMarkup = None,
        retry_after: list | None = None,
        blocked: list | None = None,
        sent_to: list | None = None,
) -> bool:
    """Отправить текст. ``sent_to`` собирает ``(chat_id, message_id)``.

    id нужен только для отзыва: без него ошибочную рассылку не удалить
    ничем — Bot API не отдаёт id уже отправленного сообщения.
    """
    try:
        msg = await bot.send_message(
            user_id,
            text,
            disable_notification=disable_notification,
            reply_markup=reply_markup,
        )
    except exceptions.TelegramBadRequest as e:
        logging.error("Target [ID:%s] BadRequest: %s", user_id, e.message)
    except exceptions.TelegramForbiddenError:
        # Не «ошибка отправки», а «этот человек больше не наш адресат».
        # Отдельным списком, чтобы рассылка сняла его с подписки: иначе
        # он остаётся в get_subscribed() навсегда и каждый цикл тратит
        # на него запрос и строку в логе.
        logging.warning("Target [ID:%s]: заблокировал бота", user_id)
        if blocked is not None:
            blocked.append(user_id)
    except exceptions.TelegramRetryAfter as e:
        # Спать здесь нельзя: send_message зовут по одному в цикле
        # рассылки, и сон на одного останавливал всех остальных. Замер
        # на стабе: 5 адресатов при delay=0.01 — 0.04 с идеала против
        # 2.06 с, потому что один 429 держал цикл. Отдаём 429 наружу,
        # цикл решает сам.
        logging.error("Target [ID:%s]: Flood limit, retry_after=%s",
                      user_id, e.retry_after)
        if retry_after is not None:
            retry_after[0] = max(retry_after[0], e.retry_after)
        return False
    except exceptions.TelegramAPIError:
        logging.exception(f"Target [ID:{user_id}]: failed")
    else:
        logging.info(f"Target [ID:{user_id}]: success")
        if sent_to is not None and getattr(msg, "message_id", None):
            sent_to.append((getattr(msg, "chat", None) and msg.chat.id or user_id,
                            msg.message_id))
        return True
    return False


async def _send_photo_by_id(bot: Bot, user_id, photo, caption: str):
    """Отправить фото по кэшу file_id, загрузив его только в первый раз.

    Возвращает ``types.Message`` или None (если заглушка бота его не дала).
    """
    key = str(photo)
    cached = _file_ids.get(key)
    if cached:
        try:
            return await bot.send_photo(user_id, cached, caption=caption)
        except exceptions.TelegramBadRequest as e:
            # file_id привязан к боту и может протухнуть: Telegram чистит
            # старые файлы. Без повтора один битый id сломал бы отправку
            # этому человеку навсегда.
            logging.warning("file_id протух для %s (%s), грузим заново", key, e.message)
            _file_ids.pop(key, None)
    msg = await bot.send_photo(user_id, FSInputFile(photo), caption=caption)
    if msg and getattr(msg, "photo", None):
        _file_ids[key] = msg.photo[-1].file_id
    return msg


async def send_photo(
        bot: Bot,
        user_id: Union[int, str],
        photo,
        caption: str = "",
        retry_after: list | None = None,
        blocked: list | None = None,
        sent_to: list | None = None,
) -> bool:
    try:
        msg = await _send_photo_by_id(bot, user_id, photo, caption)
    except exceptions.TelegramBadRequest as e:
        logging.error("Target [ID:%s] BadRequest: %s", user_id, e.message)
    except exceptions.TelegramForbiddenError:
        logging.warning("Target [ID:%s]: заблокировал бота", user_id)
        if blocked is not None:
            blocked.append(user_id)
    except exceptions.TelegramRetryAfter as e:
        # Тот же довод, что и в send_message: сон здесь держит весь
        # цикл рассылки, а не одного адресата.
        logging.error("Target [ID:%s]: Flood limit, retry_after=%s",
                      user_id, e.retry_after)
        if retry_after is not None:
            retry_after[0] = max(retry_after[0], e.retry_after)
        return False
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
        if sent_to is not None and getattr(msg, "message_id", None):
            sent_to.append((getattr(msg, "chat", None) and msg.chat.id or user_id,
                            msg.message_id))
        return True
    return False


async def broadcast_schedule(
        bot: Bot,
        items: list[tuple[Union[str, int], str, Union[str, None]]],
        rate: float = 20.0,
        blocked: list | None = None,
        sent_to: list | None = None,
) -> int:
    """Send schedule messages (text or photo+text) with rate limiting.

    ``blocked`` собирает тех, кто заблокировал бота: это не «не дошло,
    повтори», а «адресат больше не наш». Повторять им бессмысленно,
    поэтому их не кладём в failed. ``sent_to`` накапливает
    ``(chat_id, message_id)`` доставленного — это и есть право на отзыв.
    """
    if not items:
        return 0
    if blocked is None:
        blocked = []
    delay = 1.0 / max(rate, 0.1)
    sent = 0
    failed: list[tuple[Union[str, int], str, Union[str, None]]] = []
    for user_id, text, photo in items:
        # Второй уровень защиты: даже неожиданное исключение на одном
        # получателе не должно лишать расписания остальных.
        wait = [0.0]
        try:
            before = len(blocked)
            if photo:
                ok = await send_photo(bot, user_id, photo, text,
                                      retry_after=wait, blocked=blocked,
                                      sent_to=sent_to)
            else:
                ok = await send_message(bot, user_id, text,
                                        retry_after=wait, blocked=blocked,
                                        sent_to=sent_to)
            blocked_here = len(blocked) > before
        except Exception:
            logging.exception("broadcast: сбой на %s, продолжаем", user_id)
            ok = False
            blocked_here = False
        if ok:
            sent += 1
        elif not blocked_here:
            failed.append((user_id, text, photo))
        _stash_retry(wait[0])
        await asyncio.sleep(delay)

    # Один сон на всю пачку, а не на каждого получившего 429.
    if failed:
        wait = _take_retry()
        logging.warning("broadcast_schedule: %d не доставлено, ждём %.0f с",
                        len(failed), wait)
        if wait > 0:
            await asyncio.sleep(wait)
        for user_id, text, photo in failed:
            try:
                ok = (await send_photo(bot, user_id, photo, text, blocked=blocked,
                                       sent_to=sent_to)
                      if photo
                      else await send_message(bot, user_id, text, blocked=blocked,
                                              sent_to=sent_to))
            except Exception:
                logging.exception("broadcast: сбой на %s, продолжаем", user_id)
                ok = False
            if ok:
                sent += 1
    logging.info("broadcast_schedule: %d/%d sent at %.1f msg/s", sent, len(items), rate)
    return sent


async def broadcast_many(
        bot: Bot,
        items: list[tuple[Union[str, int], str]],
        rate: float = 5.0,
        sent_to: list | None = None,
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
    failed: list[tuple[Union[str, int], str]] = []
    for user_id, text in items:
        wait = [0.0]
        try:
            if await send_message(bot, user_id, text, retry_after=wait,
                                  sent_to=sent_to):
                sent += 1
            else:
                failed.append((user_id, text))
        except Exception:
            logging.exception("broadcast: сбой на %s, продолжаем", user_id)
        _stash_retry(wait[0])
        await asyncio.sleep(delay)

    # Один сон на всю пачку: retry_after от любого адресата — сигнал,
    # что лимитит весь бот, и ждать надо всем, а не по разу на каждого.
    if failed:
        wait = _take_retry()
        logging.warning("broadcast_many: %d не доставлено, ждём %.0f с",
                        len(failed), wait)
        if wait > 0:
            await asyncio.sleep(wait)
        for user_id, text in failed:
            try:
                if await send_message(bot, user_id, text, sent_to=sent_to):
                    sent += 1
            except Exception:
                logging.exception("broadcast: сбой на %s, продолжаем", user_id)
    logging.info("broadcast_many: %d/%d sent at %.1f msg/s", sent, len(items), rate)
    return sent
