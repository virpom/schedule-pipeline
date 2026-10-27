"""Группа, переехавшая из одной формы вуза в другую.

План 161. `vuz_group.name` — первичный ключ, а `replace_vuz_groups`
чистил только свою форму. При переезде `part -> full` вставка падала с
IntegrityError: в базе лежала строка с тем же именем и form="part".

Транзакция откатывалась, данные оставались целы — но
`replace_vuz_lessons` и `replace_vuz_changes` не выполнялись вовсе, и
расписание очной формы переставало обновляться. Молча: `failed`
оставался пуст, админ ничего не получал. Следующий опрос повторял то
же самое.
"""
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from infrastructure.database.models import Base
from infrastructure.database.models.vuz_group import VuzGroup
from infrastructure.database.repo.requests import RequestsRepo
from parsers import vuz
from tgbot.services import sync_vuz

G = vuz.VuzGroup


@pytest.fixture
async def repo():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    pool = async_sessionmaker(engine, expire_on_commit=False)
    async with pool() as session:
        yield RequestsRepo(session)
    await engine.dispose()


async def _forms(repo) -> dict[str, str]:
    from sqlalchemy import select
    rows = (await repo.session.execute(select(VuzGroup))).scalars()
    return {g.name: g.form for g in rows}


@pytest.mark.asyncio
async def test_part_to_full_does_not_crash(repo):
    """Группа переехала из очно-заочной в очную."""
    await sync_vuz.replace_vuz_groups(
        repo, [G(name="ММ-24оз", faculty="ММ", course=2, form="part")], "part")
    await sync_vuz.replace_vuz_groups(
        repo, [G(name="ММ-24оз", faculty="ММ", course=2, form="full")], "full")
    assert (await _forms(repo))["ММ-24оз"] == "full"


@pytest.mark.asyncio
async def test_full_to_part_does_not_crash(repo):
    """Обратное направление тоже не должно ломаться."""
    await sync_vuz.replace_vuz_groups(
        repo, [G(name="ЭЭ-26-2", faculty="ЭЭ", course=1, form="full")], "full")
    await sync_vuz.replace_vuz_groups(
        repo, [G(name="ЭЭ-26-2", faculty="ЭЭ", course=1, form="part")], "part")
    assert (await _forms(repo))["ЭЭ-26-2"] == "part"


@pytest.mark.asyncio
async def test_other_form_groups_survive(repo):
    """Чужие группы не трогаются — это была причина «чистить только свою»."""
    await sync_vuz.replace_vuz_groups(
        repo, [G(name="ММ-24оз", faculty="ММ", course=2, form="part"),
               G(name="ИП-26", faculty="ИП", course=1, form="part")], "part")
    await sync_vuz.replace_vuz_groups(
        repo, [G(name="ДП-26", faculty="ДП", course=1, form="full")], "full")
    forms = await _forms(repo)
    assert forms == {"ММ-24оз": "part", "ИП-26": "part", "ДП-26": "full"}


@pytest.mark.asyncio
async def test_removed_group_disappears(repo):
    """Группа ушла из файла — строка удаляется."""
    await sync_vuz.replace_vuz_groups(
        repo, [G(name="А-1", faculty="А", course=1, form="full")], "full")
    await sync_vuz.replace_vuz_groups(
        repo, [G(name="Б-2", faculty="Б", course=2, form="full")], "full")
    assert (await _forms(repo)) == {"Б-2": "full"}


@pytest.mark.asyncio
async def test_empty_list_clears_form(repo):
    """Пустой список: in_([]) ложно, остаётся только своя форма."""
    await sync_vuz.replace_vuz_groups(
        repo, [G(name="ММ-24оз", faculty="ММ", course=2, form="part")], "part")
    await sync_vuz.replace_vuz_groups(repo, [], "full")
    assert (await _forms(repo)) == {"ММ-24оз": "part"}
