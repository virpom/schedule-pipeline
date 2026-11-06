"""Материализация не переписывает день, содержимое которого не изменилось.

Поллер зовёт materialize каждые 5 минут. Раньше это означало запись
14 дней подряд — по 130 групп в каждом — независимо от того, менялось
что-нибудь или нет.

Замер на копии базы прода (130 групп, 14 дней):
  старый код, каждый проход   1.61 с
  новый, проход без изменений 1.29 с
Экономия скромная: почти всё время уходит на сборку слотов, а не на
запись. Но она бесплатная, и запись перестаёт держать SQLite.

Две ловушки, на которые я наступил по дороге (обе закрыты тестами):
  * пустой день в digest_by_date отсутствует — «день без пар» и «дня
    нет» выглядели одинаково, и пустые дни переписывались каждый цикл;
  * первый проход по пустой базе писал только 2 дня из 14.
"""
import asyncio
import datetime

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from infrastructure.database.models import Base
from infrastructure.database.repo.requests import RequestsRepo
from parsers.eios import BaseLesson as ParsedLesson
from tgbot.services import sync_eios


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


async def make_env():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def test_first_run_writes_whole_window():
    """Пустая база — пишем все 14 дней, включая дни без пар."""
    async def body():
        engine, pool = await make_env()
        try:
            async with pool() as db:
                repo = RequestsRepo(db)
                await sync_eios.replace_base_lessons(repo, [
                    ParsedLesson("ДП-26", 1, 1, "Математика", "Иванов И.И.")])
                assert await sync_eios.materialize(repo, days=14) == 14
        finally:
            await engine.dispose()

    run(body())


def test_second_run_writes_nothing():
    """Повторный проход на тех же данных не пишет ни одного дня."""
    async def body():
        engine, pool = await make_env()
        try:
            async with pool() as db:
                repo = RequestsRepo(db)
                await sync_eios.replace_base_lessons(repo, [
                    ParsedLesson("ДП-26", 1, 1, "Математика", "Иванов И.И.")])
                await sync_eios.materialize(repo, days=14)
                again = await sync_eios.materialize(repo, days=14)
                assert again == 0, f"переписал {again} дней без изменений"
        finally:
            await engine.dispose()

    run(body())


def test_changed_content_is_written():
    """А если пары поменялись — день перезаписывается."""
    async def body():
        engine, pool = await make_env()
        try:
            async with pool() as db:
                repo = RequestsRepo(db)
                await sync_eios.replace_base_lessons(repo, [
                    ParsedLesson("ДП-26", 1, 1, "Математика", "Иванов И.И.")])
                await sync_eios.materialize(repo, days=14)
                # Меняем предмет и убеждаемся, что день переписан.
                await sync_eios.replace_base_lessons(repo, [
                    ParsedLesson("ДП-26", 1, 1, "Физика", "Петров П.П.")])
                written = await sync_eios.materialize(repo, days=14)
                assert written >= 1, "изменение не дошло до базы"
        finally:
            await engine.dispose()

    run(body())


def test_empty_day_still_published():
    """День без пар всё равно отмечается опубликованным.

    Иначе студент видит «расписание ещё не выложено» вместо «занятий
    нет» — и ждёт публикации, которой не будет.
    """
    async def body():
        engine, pool = await make_env()
        try:
            async with pool() as db:
                repo = RequestsRepo(db)
                await sync_eios.replace_base_lessons(repo, [
                    ParsedLesson("ДП-26", 1, 1, "Математика", "Иванов И.И.")])
                await sync_eios.materialize(repo, days=14)
                today = datetime.date.today()
                # Вторник: у ДП-26 пар нет, но день должен быть отмечен.
                tuesday = next(today + datetime.timedelta(days=i) for i in range(7)
                               if (today + datetime.timedelta(days=i)).isoweekday() == 2)
                dates = await repo.schedule_files.get_dates(tuesday, tuesday)
                assert tuesday in dates, "пустой день не опубликован"
        finally:
            await engine.dispose()

    run(body())


def test_schedule_file_repo_has_get_dates():
    from infrastructure.database.repo.schedule_file import ScheduleFileRepo
    assert hasattr(ScheduleFileRepo, "get_dates")
