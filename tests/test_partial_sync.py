"""Частичный сбой синхронизации: тревога админу и честная свежесть.

Два дефекта, найденные 26.10.2026, когда сайт колледжа отдавал 404 на
файл замен девять часов:

* план 105 — сбой только писался в лог, админ не узнавал;
* план 110 — один битый файл помечал устаревшим всё расписание, и 233
  студента читали «сайт не отвечает», хотя сайт отвечал.

Здесь проверяется логика различения, без сети и без телеги.
"""
import asyncio

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from infrastructure.database.models import Base
from infrastructure.database.repo.requests import RequestsRepo
from tgbot.services import source_state, sync_eios


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


async def make_env():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def test_step_names_are_constants():
    """Имена шагов — константы, а не литералы в двух местах.

    Поллер сравнивает failed с attempted. Если имена разъедутся, условие
    «сайт отвечает, если доехал хоть один файл» начнёт врать.
    """
    assert sync_eios.STEP_OCHOE == "очное расписание"
    assert sync_eios.STEP_ZAMENY == "замены"
    assert sync_eios.STEP_BELLS == "звонки"
    assert len({sync_eios.STEP_OCHOE, sync_eios.STEP_ZAMENY,
                sync_eios.STEP_BELLS}) == 3


def test_bells_failure_does_not_escape_sync_once():
    """Падение звонков ловится _step, а не вылетает из прохода.

    Раньше блок звонков был вне _step: исключение поднималось из
    sync_once целиком, result становился None, и уже записанное очное
    расписание теряло отметку свежести — студент видел «сайт не
    отвечает», хотя очное обновилось.
    """
    import inspect

    src = inspect.getsource(sync_eios.sync_once)
    # Вызов звонков должен идти через _step, как остальные два.
    assert "_step(STEP_BELLS" in src, "звонки не обёрнуты в _step"
    # И не должны скачиваться прямо в теле sync_once.
    assert "links.bells_monday)" not in src.replace(
        "_step(STEP_BELLS, _sync_bells(session, repo, links, force, changed))", "")


def test_attempted_lists_only_requested_steps():
    """attempted содержит ровно те шаги, которые пробовали.

    Непробованный шаг (ссылки нет на странице) не попадает ни в failed,
    ни в успех. Без attempted «упали все» не отличить от «половину
    файлов убрали со страницы».
    """
    async def scenario():
        engine, pool = await make_env()
        try:
            async with pool() as db:
                repo = RequestsRepo(db)
                # Пустые ссылки: ни один шаг не пробуется.
                links = type("L", (), {
                    "ochoe": None, "zameny": None,
                    "bells_monday": None, "bells_standard": None,
                })()

                async def fake_fetch(session, config):
                    return links

                orig = sync_eios._fetch_links
                sync_eios._fetch_links = fake_fetch
                try:
                    result = await sync_eios.sync_once(None, repo, None)
                finally:
                    sync_eios._fetch_links = orig

                assert result["attempted"] == []
                assert "failed" not in result
        finally:
            await engine.dispose()
    run(scenario())


def test_partial_failure_keeps_freshness():
    """Один упавший файл из трёх — сайт жив, свежесть отмечается.

    Это и есть план 110: студент больше не видит «сайт не отвечает»,
    когда не обновился только листок замен.
    """
    async def scenario():
        engine, pool = await make_env()
        try:
            async with pool() as db:
                repo = RequestsRepo(db)
                failed = {sync_eios.STEP_ZAMENY}
                attempted = {sync_eios.STEP_OCHOE, sync_eios.STEP_ZAMENY,
                             sync_eios.STEP_BELLS}
                # Условие из poll_once, вынесенное сюда дословно.
                if attempted - failed:
                    await source_state.mark_ok(repo)

                assert not await source_state.is_stale(repo), (
                    "частичный сбой не должен помечать данные устаревшими"
                )
        finally:
            await engine.dispose()
    run(scenario())


def test_total_failure_keeps_stale():
    """Упали все запрошенные файлы — свежесть не отмечаем.

    Иначе наивная правка «отмечать всегда, когда result не None» соврёт:
    сайт жив, но ни один файл не разобрался.
    """
    async def scenario():
        engine, pool = await make_env()
        try:
            async with pool() as db:
                repo = RequestsRepo(db)
                failed = {sync_eios.STEP_OCHOE, sync_eios.STEP_ZAMENY,
                          sync_eios.STEP_BELLS}
                attempted = set(failed)
                if attempted - failed:
                    await source_state.mark_ok(repo)

                assert await source_state.is_stale(repo), (
                    "полный сбой должен оставить данные устаревшими"
                )
        finally:
            await engine.dispose()
    run(scenario())


def test_partial_alert_has_its_own_key():
    """Тревога о частичном сбое не глушит тревогу о структуре.

    alert_* хранит хеш последнего текста. Один ключ на две разные
    проблемы — они будут затирать друг друга.
    """
    import inspect
    from tgbot.services import poller

    src = inspect.getsource(poller._report_partial_failure)
    assert '"partial"' in src, "частичный сбой должен идти в свой ключ"
    assert '"structure"' not in src, "не смешивать с тревогой о структуре"

    # И clear должен снимать тот же ключ.
    poll_once_src = inspect.getsource(poller.poll_once)
    assert 'alerts.clear(bot, repo, config, "partial"' in poll_once_src
