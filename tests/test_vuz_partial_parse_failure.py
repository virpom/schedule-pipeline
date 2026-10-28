"""Сломанный лист одной формы не блокирует другую.

План 156. `sync_once` идёт по двум файлам (очная и очно-заочная).
При `VuzParseError` стоял `raise`, и цикл обрывался: если у очной формы
поехала структура, очно-заочная в этом проходе уже не обновлялась,
хотя у неё свой файл и своя структура.

Тревога при этом должна остаться — она работает через `failed`.
"""
import inspect

from tgbot.services import sync_vuz


def test_parse_error_does_not_raise():
    """`raise` в ветке VuzParseError обрывал вторую форму."""
    src = inspect.getsource(sync_vuz.sync_once)
    block = src.split("VuzParseError as exc")[1]
    # до конца этого except-блока
    block = block.split("except ")[0]
    assert "raise" not in block, "сломанный лист по-прежнему обрывает проход"
    assert "continue" in block, "нет перехода к следующей форме"


def test_failed_accumulates():
    """Форма с ошибкой попадает в `failed` — по нему поллер тревожит."""
    src = inspect.getsource(sync_vuz.sync_once)
    block = src.split("VuzParseError as exc")[1].split("except ")[0]
    assert 'result["failed"].append(form)' in block


def test_two_forms_exist():
    """Смысл правки — именно в том, что форм больше одной."""
    assert len(sync_vuz.FILES) >= 2


def test_poller_reports_partial():
    from tgbot.services import poller

    src = inspect.getsource(poller)
    assert "vuz_result.get(\"failed\")" in src, "поллер не видит ошибку формы"


def test_first_form_failure_second_form_runs():
    """Сквозная проверка: упала первая — вторая всё равно разобрана."""
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from infrastructure.database.models import Base
    from infrastructure.database.repo.requests import RequestsRepo

    calls = []

    def fake_parse(data, form):
        calls.append(form)
        if form == "full":
            raise sync_vuz.vuz.VuzParseError("структура поехала")

        class P:
            groups = []
            lessons = []
            changes = []
        return P()

    class _Resp:
        def raise_for_status(self):
            pass

        async def read(self):
            return b"x"

    class _Session:
        def get(self, url, **kwargs):
            class _Ctx:
                async def __aenter__(self_inner):
                    return _Resp()

                async def __aexit__(self_inner, *a):
                    return False
            return _Ctx()

    async def run():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        pool = async_sessionmaker(engine, expire_on_commit=False)
        real_parse = sync_vuz.vuz.parse
        sync_vuz.vuz.parse = fake_parse
        try:
            async with pool() as db:
                res = await sync_vuz.sync_once(_Session(), RequestsRepo(db), force=True)
        finally:
            sync_vuz.vuz.parse = real_parse
            await engine.dispose()
        return res

    res = asyncio.run(run())
    assert calls, "разбор вообще не запускался"
    assert len(calls) == 2, f"вторая форма не разобрана: {calls}"
    assert res["failed"], "ошибка формы не попала в failed"
