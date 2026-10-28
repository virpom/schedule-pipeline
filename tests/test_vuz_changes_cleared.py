"""Замены вуза стираются, когда файл пришёл без них (ранг 77).

replace_vuz_changes выходил с `if not changes: return 0` ДО удаления
старых записей. Файл, перевыложенный без замен, оставлял их
применяться к расписанию вуза — и заметить это можно было только
глазами.

У колледжа (replace_substitutions) та же задача решена иначе: удаление
идёт всегда, пустой список просто ничего не добавляет.
"""
import asyncio
import datetime

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from infrastructure.database.models import Base, VuzGroup
from infrastructure.database.repo.requests import RequestsRepo
from tgbot.services import sync_vuz


@pytest.fixture()
def env(tmp_path):
    async def build():
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/db.sqlite")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        sf = async_sessionmaker(engine, expire_on_commit=False)
        return engine, sf

    return build


def _run(coro):
    return asyncio.run(coro)


def test_empty_file_clears_vuz_changes(env):
    """Файл перевыложен без замен — старые не должны применяться."""
    async def body():
        engine, sf = await env()
        try:
            async with sf() as s:
                repo = RequestsRepo(s)
                d = datetime.date.today() + datetime.timedelta(days=2)
                s.add(VuzGroup(name="ИП-26@vuz", form="full", faculty="ФЭМ", course=1))
                await s.commit()
                await repo.substitutions.set(
                    d, "ИП-26@vuz", 3, "replace", "Спорная замена",
                    source=sync_vuz.SOURCE_VUZ)

                before = await repo.substitutions.get_for_date("ИП-26@vuz", d)
                assert before, "подготовка: замены нет"

                await sync_vuz.replace_vuz_changes(repo, [], "full")

                after = await repo.substitutions.get_for_date("ИП-26@vuz", d)
                assert not after, f"замена осталась: {[(x.subject) for x in after]}"
        finally:
            await engine.dispose()

    _run(body())


def test_other_form_untouched(env):
    """Чистим только свою форму: второй файл не трогает замены первого."""
    async def body():
        engine, sf = await env()
        try:
            async with sf() as s:
                repo = RequestsRepo(s)
                d = datetime.date.today() + datetime.timedelta(days=2)
                s.add_all([VuzGroup(name="ИП-26@vuz", form="full",
                                    faculty="ФЭМ", course=1),
                           VuzGroup(name="ИВТ-26@vuz", form="part",
                                    faculty="ФИТ", course=1)])
                await s.commit()
                await repo.substitutions.set(d, "ИВТ-26@vuz", 2, "replace",
                                             "Чужая форма", source=sync_vuz.SOURCE_VUZ)

                await sync_vuz.replace_vuz_changes(repo, [], "full")

                left = await repo.substitutions.get_for_date("ИВТ-26@vuz", d)
                assert left, "снесли замены второй формы"
        finally:
            await engine.dispose()

    _run(body())
