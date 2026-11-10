"""Сессия бота, которая переживает переподключение ВПН.

Telegram в РФ доступен только через туннель на роутере, а туннель
периодически переподключается: sing-box теряет fakeip-записи и
пересоздаёт их с другими адресами.

aiohttp при этом держит соединение, которое уже мертво. aiogram ловит
`TelegramNetworkError` и повторяет запрос через 5 секунд — но сессию не
пересоздаёт: флаг `_should_reset_connector` остаётся False, и следующая
попытка идёт в тот же мёртвый сокет. Так бот висит до ручного
перезапуска.

Прод, 10.11.2026: контейнер простоял 14 часов, 37 попыток подряд
«Connection reset by peer», при том что `aiohttp` из того же контейнера
в тот же момент получал 200 пять раз из пяти. Перезапуск помог сразу.

Здесь сессия сбрасывается сама при первой же сетевой ошибке.
"""
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramNetworkError


class ReconnectingSession(AiohttpSession):
    """AiohttpSession, которая пересоздаёт соединение после сбоя."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        # aiogram кеширует DNS на час (обход их issue #1500). С fakeip
        # это вредно: запись 198.18.x.x живёт в sing-box, а не в
        # aiohttp, и после перезапуска туннеля тот же адрес может
        # указывать уже на другой хост. Минута — компромисс: fakeip
        # успевает протухнуть, а лишних запросов почти нет.
        self._connector_init["ttl_dns_cache"] = 60

    async def make_request(self, bot, method, timeout=None):
        try:
            return await super().make_request(bot, method, timeout)
        except TelegramNetworkError:
            # aiogram перехватывает ClientError сам и заворачивает в
            # TelegramNetworkError, поэтому ловим именно его: голый
            # aiohttp.ClientError сюда уже не долетит.
            #
            # Флаг приватный, но другого способа пересоздать коннектор
            # у aiogram нет. Тест tests/test_reconnecting_session.py
            # упадёт, если атрибут переименуют при обновлении.
            self._should_reset_connector = True
            raise
