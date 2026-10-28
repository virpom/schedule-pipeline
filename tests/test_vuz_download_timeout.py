"""Скачивание файла вуза с таймаутом (план 088).

sync_vuz._download звался без timeout=. ClientSession в poller.py
создаётся без своего таймаута, поэтому aiohttp брал дефолт — 5 минут
на чтение. Файл вуза крупнее колледжного, проход мог встать до 10
минут молча, задерживая рассылку и следующий опрос.

У соседа sync_eios таймаут был с самого начала — потому и незаметно.
"""
import inspect


from tgbot.services import sync_eios, sync_vuz


def _fake_session(timeouts: list):
    class _Resp:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def read(self):
            return b"data"

        def raise_for_status(self):
            pass

    class _Session:
        def get(self, url, **kwargs):
            timeouts.append(kwargs.get("timeout"))
            return _Resp()

    return _Session()


def test_vuz_passes_timeout():
    timeouts: list = []
    import asyncio
    got = asyncio.run(sync_vuz._download(_fake_session(timeouts), "http://x/y.xls"))
    assert got == b"data"
    assert timeouts == [60], f"timeout={timeouts}"


def test_eios_passes_timeout():
    timeouts: list = []
    import asyncio
    got = asyncio.run(sync_eios._download(_fake_session(timeouts), "http://x/y.docx"))
    assert got == b"data"
    assert timeouts == [60], f"timeout={timeouts}"


def test_both_raise_status():
    """sync_vuz раньше вызывал raise_for_status отдельно — теперь в get."""
    for mod in (sync_eios, sync_vuz):
        body = inspect.getsource(mod._download)
        assert "raise_for_status=True" in body, mod.__name__


def test_vuz_timeout_matches_neighbour():
    """Один и тот же таймаут у обеих загрузок — иначе разъедутся снова."""
    import re
    def _t(mod):
        m = re.search(r"timeout=(\d+)", inspect.getsource(mod._download))
        assert m, mod.__name__
        return m.group(1)
    assert _t(sync_vuz) == _t(sync_eios)


def test_timeout_is_finite():
    import re
    m = re.search(r"timeout=(\d+)", inspect.getsource(sync_vuz._download))
    assert int(m.group(1)) <= 120
