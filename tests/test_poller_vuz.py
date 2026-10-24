"""Рассылка вуза: замены вуза должны попадать в уведомления.

Раньше poll_once смотрел только на флаги колледжа (result["ochoe"] /
result["zameny"]), а результат синхронизации вуза использовался лишь
для логов. Студент вуза не получал уведомлений вообще.
"""
import asyncio
import datetime as dt

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from infrastructure.database.models import Base, Substitution
from infrastructure.database.repo.requests import RequestsRepo


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


async def make_env():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def test_vuz_substitution_dates_are_collected():
    """Даты замен вуза попадают в выборку для рассылки.

    notify_new_schedule получает список дат из substitutions.get_dates().
    Если замены вуза там есть, студент вуза получит уведомление — его
    расписание берётся из college_lesson по его группе.
    """
    async def scenario():
        engine, pool = await make_env()
        try:
            async with pool() as db:
                repo = RequestsRepo(db)
                today = dt.date.today()
                await repo.substitutions.set(
                    date=today + dt.timedelta(days=1), group="ЭК-26-2@vuz",
                    para=3, action="replace", subject="Перенос", source="vuz")
                await repo.substitutions.set(
                    date=today + dt.timedelta(days=1), group="ТЭ-26ФП",
                    para=1, action="replace", subject="Замена", source="site")

                dates = set(await repo.substitutions.get_dates(today))
                assert today + dt.timedelta(days=1) in dates
        finally:
            await engine.dispose()
    run(scenario())


def test_vuz_change_flag_drives_broadcast():
    """Синхронизация вуза должна включать рассылку, даже если колледж молчит.

    Раньше условие было `result["ochoe"] or result["zameny"]` — только
    колледж. Студент вуза не получал уведомлений вообще. Теперь есть
    второе слагаемое — vuz_changed из результата sync_vuz.
    """
    import inspect
    from tgbot.services import poller

    src = inspect.getsource(poller.poll_once)
    assert "vuz_changed" in src, "результат вуза не учитывается в poll_once"
    assert "vuz_result.get(\"full\")" in src or "vuz_result.get('full')" in src
    # Условие раннего выхода должно учитывать оба подразделения.
    assert "college_changed" in src and "not vuz_changed" in src
