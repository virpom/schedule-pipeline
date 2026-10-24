"""Синхронизация вуза: запись в базу и фильтрация по неделям."""
import asyncio
import datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from infrastructure.database.models import Base, BaseLesson, Substitution, VuzGroup
from infrastructure.database.repo.requests import RequestsRepo
from parsers import vuz
from tgbot.services import sync_vuz


@pytest.fixture
def anyio_backend():
    return "asyncio"


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


class Env:
    """In-memory база с готовым репозиторием."""

    def __init__(self, engine, pool):
        self.engine = engine
        self.pool = pool

    async def close(self):
        await self.engine.dispose()


async def make_env():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return Env(engine, async_sessionmaker(engine, expire_on_commit=False))


# --- недели ------------------------------------------------------------------

def test_weeks_roundtrip():
    weeks = (6, 8, 10, 12)
    assert sync_vuz.str_to_weeks(sync_vuz.weeks_to_str(weeks)) == weeks


def test_weeks_empty_roundtrip():
    assert sync_vuz.weeks_to_str(()) == ""
    assert sync_vuz.str_to_weeks("") == ()


def test_vuz_week_from_anchor():
    """Неделя якоря — первая, дальше по семь дней."""
    anchor = datetime.date(2026, 8, 31)
    assert sync_vuz.vuz_week(anchor, anchor) == 1
    assert sync_vuz.vuz_week(anchor + datetime.timedelta(days=7), anchor) == 2
    assert sync_vuz.vuz_week(anchor + datetime.timedelta(days=6), anchor) == 1
    assert sync_vuz.vuz_week(anchor + datetime.timedelta(days=13), anchor) == 2


# --- запись ------------------------------------------------------------------

def test_replace_lessons_writes_and_counts():
    async def scenario():
        env = await make_env()
        try:
            async with env.pool() as db:
                repo = RequestsRepo(db)
                lessons = [
                    vuz.VuzLesson("ЭК-23@vuz", 1, 1, "ANY", "Математика",
                                  "Иванов И.И.", weeks=(6, 8)),
                    vuz.VuzLesson("ЭК-23@vuz", 1, 1, "ANY", "Физика",
                                  "Петров П.П.", weeks=(5, 7)),
                ]
                n = await sync_vuz.replace_vuz_lessons(repo, lessons)
                assert n == 2
                rows = (await db.execute(select(BaseLesson))).scalars().all()
                assert len(rows) == 2
                assert {r.weeks for r in rows} == {"6,8", "5,7"}
        finally:
            await env.close()
    run(scenario())


def test_same_slot_different_weeks_both_stored():
    """Главное требование вуза: два предмета в одном слоте на разных неделях."""
    async def scenario():
        env = await make_env()
        try:
            async with env.pool() as db:
                repo = RequestsRepo(db)
                await sync_vuz.replace_vuz_lessons(repo, [
                    vuz.VuzLesson("ЭК-23@vuz", 1, 7, "ANY", "Экономика",
                                  weeks=(6, 8, 10)),
                    vuz.VuzLesson("ЭК-23@vuz", 1, 7, "ANY", "Презентации",
                                  weeks=(5, 7, 9)),
                ])
                rows = (await db.execute(select(BaseLesson))).scalars().all()
                assert len(rows) == 2, "одна пара затёрла другую"
        finally:
            await env.close()
    run(scenario())


def test_replace_removes_stale_site_rows():
    """Пару убрали из файла — она должна исчезнуть, а не висеть вечно."""
    async def scenario():
        env = await make_env()
        try:
            async with env.pool() as db:
                repo = RequestsRepo(db)
                await sync_vuz.replace_vuz_lessons(repo, [
                    vuz.VuzLesson("ЭК-23@vuz", 1, 1, "ANY", "Старая", weeks=(1,)),
                ])
                await sync_vuz.replace_vuz_lessons(repo, [
                    vuz.VuzLesson("ЭК-23@vuz", 1, 1, "ANY", "Новая", weeks=(1,)),
                ])
                rows = (await db.execute(select(BaseLesson))).scalars().all()
                assert [r.subject for r in rows] == ["Новая"]
        finally:
            await env.close()
    run(scenario())


def test_manual_edit_survives_sync():
    """Ручная правка старосты важнее файла — её не перетираем."""
    async def scenario():
        env = await make_env()
        try:
            async with env.pool() as db:
                repo = RequestsRepo(db)
                await repo.base_lessons.upsert(
                    "ЭК-23@vuz", "ANY", 1, 1, "Ручная", weeks="1",
                    source="manual")
                await sync_vuz.replace_vuz_lessons(repo, [
                    vuz.VuzLesson("ЭК-23@vuz", 1, 1, "ANY", "Сайт", weeks=(1,)),
                ])
                rows = (await db.execute(select(BaseLesson))).scalars().all()
                assert [r.subject for r in rows] == ["Ручная"]
        finally:
            await env.close()
    run(scenario())


def test_vuz_sync_does_not_touch_college():
    """Синхронизация вуза не должна сносить расписание колледжа."""
    async def scenario():
        env = await make_env()
        try:
            async with env.pool() as db:
                repo = RequestsRepo(db)
                await repo.base_lessons.upsert(
                    "ЭК-23", "ODD", 1, 1, "Колледж", source="site")
                await sync_vuz.replace_vuz_lessons(repo, [
                    vuz.VuzLesson("ЭК-23@vuz", 1, 1, "ANY", "Вуз", weeks=(1,)),
                ])
                rows = (await db.execute(select(BaseLesson))).scalars().all()
                groups = {r.group for r in rows}
                assert groups == {"ЭК-23", "ЭК-23@vuz"}
        finally:
            await env.close()
    run(scenario())


def test_groups_saved_with_faculty():
    async def scenario():
        env = await make_env()
        try:
            async with env.pool() as db:
                repo = RequestsRepo(db)
                n = await sync_vuz.replace_vuz_groups(repo, [
                    vuz.VuzGroup("ЭК-23@vuz", "FEU", 2, "full"),
                    vuz.VuzGroup("ГТ-23@vuz", "GTF", 2, "full"),
                ])
                assert n == 2
                rows = (await db.execute(select(VuzGroup))).scalars().all()
                assert {r.faculty for r in rows} == {"FEU", "GTF"}
        finally:
            await env.close()
    run(scenario())


def test_changes_saved_as_substitutions():
    async def scenario():
        env = await make_env()
        try:
            async with env.pool() as db:
                repo = RequestsRepo(db)
                await sync_vuz.replace_vuz_changes(repo, [
                    vuz.VuzChange("ЭК-23@vuz", datetime.date(2026, 11, 9), 1,
                                  "История", "Иванов И.И."),
                ])
                rows = (await db.execute(select(Substitution))).scalars().all()
                assert len(rows) == 1
                assert rows[0].source == "vuz"
                assert rows[0].date == datetime.date(2026, 11, 9)
        finally:
            await env.close()
    run(scenario())


# --- чтение по неделям -------------------------------------------------------

def test_get_day_filters_by_week():
    """На разных неделях — разные предметы в одном слоте."""
    async def scenario():
        env = await make_env()
        try:
            async with env.pool() as db:
                repo = RequestsRepo(db)
                await sync_vuz.replace_vuz_lessons(repo, [
                    vuz.VuzLesson("ЭК-23@vuz", 1, 7, "ANY", "Экономика",
                                  weeks=(6, 8)),
                    vuz.VuzLesson("ЭК-23@vuz", 1, 7, "ANY", "Презентации",
                                  weeks=(5, 7)),
                ])
                week5 = await repo.base_lessons.get_day("ЭК-23@vuz", 1, "ANY", week=5)
                week6 = await repo.base_lessons.get_day("ЭК-23@vuz", 1, "ANY", week=6)
                assert [r.subject for r in week5] == ["Презентации"]
                assert [r.subject for r in week6] == ["Экономика"]
        finally:
            await env.close()
    run(scenario())


def test_get_day_without_week_returns_all():
    """Без номера недели ничего не теряем — иначе часть пар исчезнет."""
    async def scenario():
        env = await make_env()
        try:
            async with env.pool() as db:
                repo = RequestsRepo(db)
                await sync_vuz.replace_vuz_lessons(repo, [
                    vuz.VuzLesson("ЭК-23@vuz", 1, 7, "ANY", "Экономика",
                                  weeks=(6, 8)),
                    vuz.VuzLesson("ЭК-23@vuz", 1, 7, "ANY", "Презентации",
                                  weeks=(5, 7)),
                ])
                rows = await repo.base_lessons.get_day("ЭК-23@vuz", 1, "ANY")
                assert len(rows) == 2
        finally:
            await env.close()
    run(scenario())


def test_anchor_read_write():
    async def scenario():
        env = await make_env()
        try:
            async with env.pool() as db:
                repo = RequestsRepo(db)
                assert await sync_vuz.get_anchor(repo) == sync_vuz.DEFAULT_ANCHOR
                await sync_vuz.set_anchor(repo, datetime.date(2027, 9, 6))
                assert await sync_vuz.get_anchor(repo) == datetime.date(2027, 9, 6)
        finally:
            await env.close()
    run(scenario())


def test_broken_anchor_falls_back_to_default():
    """Испорченная настройка не должна ронять показ расписания."""
    async def scenario():
        env = await make_env()
        try:
            async with env.pool() as db:
                repo = RequestsRepo(db)
                await repo.settings.set(sync_vuz.ANCHOR_KEY, "не дата")
                assert await sync_vuz.get_anchor(repo) == sync_vuz.DEFAULT_ANCHOR
        finally:
            await env.close()
    run(scenario())
