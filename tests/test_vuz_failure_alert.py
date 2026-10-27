"""Сбой синхронизации вуза тревожит админа, а не только лог.

План 016. У колледжа сбой шёл через `_report_failure`, а у вуза —
`except Exception: logging.exception(...)`. `VuzParseError` уходил в
этот общий перехват, и админ не узнавал, что структура файла вуза
сломалась: бот молча работал на старых данных, пока не кончится окно
14 дней.

Админ видел проблему только в `/stats`, если сам зайдёт.
"""
import inspect

from parsers.vuz import VuzParseError
from tgbot.services import poller


def test_report_failure_knows_vuz_error():
    """_report_failure различает VuzParseError, а не только EiosParseError."""
    src = inspect.getsource(poller._report_failure)
    assert "VuzParseError" in src, "VuzParseError не учитывается"
    assert "EiosParseError" in src, "потеряна обработка колледжа"


def test_vuz_sync_calls_report_failure():
    """Сбой вуза идёт тем же путём, что и колледж."""
    src = inspect.getsource(poller.poll_once)
    vuz_part = src[src.index("sync_vuz.sync_once"):]
    vuz_part = vuz_part[:vuz_part.index("sync_eios.sync_once")]
    assert "_report_failure" in vuz_part, "сбой вуза остаётся без тревоги"


def test_vuz_exception_is_logged_not_swallowed():
    src = inspect.getsource(poller.poll_once)
    vuz_part = src[src.index("sync_vuz.sync_once"):]
    vuz_part = vuz_part[:vuz_part.index("sync_eios.sync_once")]
    assert "logging.exception" not in vuz_part, \
        "двойное логирование: warning + exception"


def test_vuz_parse_error_is_runtime_error():
    """Предпосылка: VuzParseError не подкласс EiosParseError."""
    from parsers.eios import EiosParseError
    assert not issubclass(VuzParseError, EiosParseError)


def test_college_text_unchanged():
    """Сообщение для колледжа не должно получить «вуза»."""
    src = inspect.getsource(poller._report_failure)
    assert 'where = "вуза" if isinstance(error, vuz.VuzParseError) else ""' in src


def test_vuz_imported():
    assert poller.vuz.VuzParseError is VuzParseError
