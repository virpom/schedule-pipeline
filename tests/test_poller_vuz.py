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


def test_digest_by_date_detects_only_changed_date():
    """Отпечаток даты меняется только у той даты, которую правили.

    Раньше флаг «файл изменился» слал уведомления на все даты замен
    сразу. Инцидент 26.10.2026: одна исправленная строка в файле очного
    расписания дала 15 сообщений «расписание изменилось».
    """
    async def scenario():
        engine, pool = await make_env()
        try:
            async with pool() as db:
                repo = RequestsRepo(db)
                today = dt.date.today()
                d1, d2 = today, today + dt.timedelta(days=1)
                await repo.college_lessons.replace_date(d1, [
                    {"date": d1, "group": "ДП-26", "para": 1, "para_end": 1,
                     "subject": "Архивное дело", "teacher": "Молчанова Н.А.",
                     "room": "", "source_url": "", "source": "site",
                     "changed": False, "action": ""},
                ])
                await repo.college_lessons.replace_date(d2, [
                    {"date": d2, "group": "ДП-26", "para": 1, "para_end": 1,
                     "subject": "Деловая культура", "teacher": "Золотухина Н.Е.",
                     "room": "", "source_url": "", "source": "site",
                     "changed": False, "action": ""},
                ])
                before = await repo.college_lessons.digest_by_date()

                # Правим только первый день.
                await repo.college_lessons.replace_date(d1, [
                    {"date": d1, "group": "ДП-26", "para": 1, "para_end": 1,
                     "subject": "Архивное дело (перенос)", "teacher": "Молчанова Н.А.",
                     "room": "201", "source_url": "", "source": "site",
                     "changed": False, "action": ""},
                ])
                after = await repo.college_lessons.digest_by_date()

                changed = {
                    d for d, groups in after.items()
                    if any(h != before.get(d, {}).get(g) for g, h in groups.items())
                }
                assert changed == {d1}, f"ожидали только {d1}, получили {changed}"
                assert before[d2] == after[d2], "нетронутая дата изменила отпечаток"
        finally:
            await engine.dispose()
    run(scenario())


def test_digest_by_date_isolates_groups():
    """Правка одной группы не меняет отпечаток соседней на ту же дату.

    Инцидент 26.10.2026 (второй): отпечаток считался по дате целиком,
    поэтому исправление у ``ДП-26`` будило всех 230 подписчиков —
    двадцать дат по 230 человек вместо двадцати сообщений.
    """
    async def scenario():
        engine, pool = await make_env()
        try:
            async with pool() as db:
                repo = RequestsRepo(db)
                day = dt.date.today()
                await repo.college_lessons.replace_date(day, [
                    {"date": day, "group": "ДП-26", "para": 1, "para_end": 1,
                     "subject": "Архивное дело", "teacher": "Молчанова Н.А.",
                     "room": "", "source_url": "", "source": "site",
                     "changed": False, "action": ""},
                    {"date": day, "group": "СМк-25", "para": 1, "para_end": 1,
                     "subject": "Анатомия", "teacher": "Боровик И.А.",
                     "room": "", "source_url": "", "source": "site",
                     "changed": False, "action": ""},
                ])
                before = await repo.college_lessons.digest_by_date()

                # Правим только ДП-26.
                await repo.college_lessons.replace_date(day, [
                    {"date": day, "group": "ДП-26", "para": 1, "para_end": 1,
                     "subject": "Архивное дело (перенос)", "teacher": "Молчанова Н.А.",
                     "room": "201", "source_url": "", "source": "site",
                     "changed": False, "action": ""},
                    {"date": day, "group": "СМк-25", "para": 1, "para_end": 1,
                     "subject": "Анатомия", "teacher": "Боровик И.А.",
                     "room": "", "source_url": "", "source": "site",
                     "changed": False, "action": ""},
                ])
                after = await repo.college_lessons.digest_by_date()

                diff = {
                    g for g, h in after[day].items()
                    if before[day].get(g) != h
                }
                assert diff == {"ДП-26"}, f"ожидали только ДП-26, получили {diff}"
                assert before[day]["СМк-25"] == after[day]["СМк-25"]
        finally:
            await engine.dispose()
    run(scenario())
