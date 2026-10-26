"""Глобальный обработчик ошибок: пользователь получает ответ, а не тишину.

План 022. Без него исключение в обработчике aiogram пишет traceback в
лог и на этом всё: ``cb.answer()`` не вызывается, спиннер на кнопке
висит до таймаута, человек видит «ничего не произошло» и жмёт снова.
Для обычного сообщения ещё хуже — оно остаётся без ответа, и непонятно,
дошло ли.

Достижимых путей много и все настоящие: ``callback_data`` приходит от
клиента и не подписан (``ed:bday:99`` → ``IndexError``), ``database is
locked`` под нагрузкой, ``None`` из репозитория. Обработчик закрывает их
все сразу, включая будущие, — поэтому он важнее точечной валидации.
"""
import logging

from aiogram import Bot
from aiogram.types import CallbackQuery, ErrorEvent, Message

from config import Config

TEXT_CALLBACK = "⚠️ Что-то пошло не так. Попробуй ещё раз или вернись в меню."
TEXT_MESSAGE = "⚠️ Не получилось обработать. Попробуй ещё раз."


async def on_error(event: ErrorEvent, bot: Bot, config: Config) -> None:
    """Ответить пользователю и сообщить админу.

    ``config`` приходит из ``workflow_data`` диспетчера: обработчик ошибок
    висит на ``dp.update``, выше DatabaseMiddleware, поэтому ``repo`` в
    данных нет — и не нужен.

    Полный traceback в Telegram не уходит: в тексте исключений бывают
    токены и данные пользователей. Админу — только тип и место, где
    traceback искать.
    """
    exc = event.exception
    logging.exception("необработанная ошибка", exc_info=exc)

    update = event.update.event
    try:
        if isinstance(update, CallbackQuery):
            # show_alert, а не всплывающее уведомление: иначе человек
            # не поймёт, почему ничего не открылось.
            await update.answer(TEXT_CALLBACK, show_alert=True)
        elif isinstance(update, Message):
            await update.answer(TEXT_MESSAGE)
    except Exception:
        # Ответить не вышло (сообщение удалено, бот заблокирован) —
        # это не повод падать внутри обработчика ошибок.
        logging.exception("не удалось ответить пользователю после ошибки")

    where = f"{type(exc).__name__} в {_place(exc)}"
    for admin_id in config.tg_bot.admin_ids:
        try:
            await bot.send_message(admin_id, f"⚠️ Ошибка в боте: {where}")
        except Exception:
            # Админ мог заблокировать бота — молча пропускаем.
            pass


def _place(exc: BaseException) -> str:
    """Последний кадр трейсбека: файл и строка.

    Без этого «TypeError» админу бесполезен — непонятно, где искать.
    """
    tb = exc.__traceback__
    if tb is None:
        return "?"
    last = tb
    while last.tb_next is not None:
        last = last.tb_next
    name = last.tb_frame.f_code.co_filename.rsplit("/", 1)[-1]
    return f"{name}:{last.tb_lineno}"
