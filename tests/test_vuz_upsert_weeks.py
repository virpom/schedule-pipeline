"""Правка вузовского слота не создаёт дубль.

План 154. `upsert` ключуется по пяти полям, включая `weeks`. У колледжа
`weeks` всегда пусто — совпадает с дефолтом. У вуза 1340 из 1971 строк
имеют непустой список недель, поэтому `upsert(..., weeks="")` не находит
строку и делает INSERT.

Результат для студента: пара дважды — исправленная (видна на всех
неделях, т.к. пустой weeks = «каждую неделю») и исходная.

`delete_slot` ломался так же: искал weeks='' и не удалял ничего.
"""
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from infrastructure.database.models import Base
from infrastructure.database.repo.requests import RequestsRepo

G = "АП-25оз@vuz"
PARITY = "ANY"
WD = 2
PARA = 7
WEEKS = "9,10,11,12"


@pytest.fixture
async def repo():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    pool = async_sessionmaker(engine, expire_on_commit=False)
    async with pool() as session:
        yield RequestsRepo(session)
    await engine.dispose()


@pytest.mark.asyncio
async def test_default_weeks_creates_duplicate(repo):
    """Подтверждение дефекта: с weeks='' появляется вторая строка."""
    await repo.base_lessons.upsert(G, PARITY, WD, PARA, "Оригинал", weeks=WEEKS)
    await repo.base_lessons.upsert(G, PARITY, WD, PARA, "Правка", weeks="")
    rows = await repo.base_lessons.get_day(G, WD, PARITY)
    para7 = [r for r in rows if r.para == PARA]
    assert len(para7) == 2, "ожидался дубль — схема изменилась?"


@pytest.mark.asyncio
async def test_matching_weeks_updates_in_place(repo):
    """Правка с тем же weeks обновляет строку, а не добавляет."""
    await repo.base_lessons.upsert(G, PARITY, WD, PARA, "Оригинал", weeks=WEEKS)
    await repo.base_lessons.upsert(G, PARITY, WD, PARA, "Правка", weeks=WEEKS)
    rows = await repo.base_lessons.get_day(G, WD, PARITY)
    para7 = [r for r in rows if r.para == PARA]
    assert len(para7) == 1, "дубль вместо обновления"
    assert para7[0].subject == "Правка"


@pytest.mark.asyncio
async def test_delete_slot_with_weeks(repo):
    """delete_slot с weeks удаляет нужную строку."""
    await repo.base_lessons.upsert(G, PARITY, WD, PARA, "Оригинал", weeks=WEEKS)
    await repo.base_lessons.delete_slot(G, PARITY, WD, PARA, weeks=WEEKS)
    rows = await repo.base_lessons.get_day(G, WD, PARITY)
    assert not [r for r in rows if r.para == PARA]


@pytest.mark.asyncio
async def test_delete_slot_default_weeks_misses(repo):
    """Подтверждение дефекта: дефолтный weeks не удаляет вузовскую строку."""
    await repo.base_lessons.upsert(G, PARITY, WD, PARA, "Оригинал", weeks=WEEKS)
    await repo.base_lessons.delete_slot(G, PARITY, WD, PARA)
    rows = await repo.base_lessons.get_day(G, WD, PARITY)
    assert [r for r in rows if r.para == PARA], "удалилось — условие изменилось"


def test_editor_save_passes_weeks():
    import inspect

    from tgbot.handlers import editor

    src = inspect.getsource(editor._save_base)
    assert "weeks=weeks" in src, "_save_base не передаёт weeks"
    assert 'old_slot.weeks or ""' in src, "weeks не берётся из правимой строки"


def test_editor_delete_passes_weeks():
    import inspect

    from tgbot.handlers import editor

    src = inspect.getsource(editor.cb_delete_base) \
        if hasattr(editor, "cb_delete_base") else \
        "".join(inspect.getsource(f) for n, f in inspect.getmembers(editor, inspect.isfunction)
                if "delete_slot" in inspect.getsource(f))
    assert "weeks=" in src, "delete_slot вызывается без weeks"


def test_undo_passes_weeks():
    import inspect

    from tgbot.handlers import editor

    src = inspect.getsource(editor.cb_undo)
    assert "weeks=old.get" in src, "откат upsert не передаёт weeks"
    assert 'new.get("weeks"' in src, "откат удаления не передаёт weeks"
