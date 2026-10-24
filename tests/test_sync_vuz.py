"""Синхронизация вуза: запись в базу и фильтрация по неделям."""
import asyncio
import datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from infrastructure.database.models import (Base, BaseLesson, CollegeLesson,
                                    Substitution, VuzGroup)
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
                n = await sync_vuz.replace_vuz_lessons(repo, lessons, "full")
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
                ], "full")
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
                ], "full")
                await sync_vuz.replace_vuz_lessons(repo, [
                    vuz.VuzLesson("ЭК-23@vuz", 1, 1, "ANY", "Новая", weeks=(1,)),
                ], "full")
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
                ], "full")
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
                ], "full")
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
                ], "full")
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
                ], "full")
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
                ], "full")
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
                ], "full")
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


# --- формы обучения ----------------------------------------------------------

def test_forms_do_not_wipe_each_other():
    """Очная и очно-заочная лежат в одной таблице.

    Первый прогон на проде: после загрузки второго файла осталась только
    очно-заочная — общий delete снёс очную. Формы должны чистить только
    свои строки.
    """
    async def scenario():
        env = await make_env()
        try:
            async with env.pool() as db:
                repo = RequestsRepo(db)
                full_groups = [vuz.VuzGroup("ЭК-23@vuz", "FEU", 2, "full")]
                part_groups = [vuz.VuzGroup("ЭК-23оз@vuz", "FEU", 2, "part")]

                await sync_vuz.replace_vuz_groups(repo, full_groups, "full")
                await sync_vuz.replace_vuz_lessons(repo, [
                    vuz.VuzLesson("ЭК-23@vuz", 1, 1, "ANY", "Очная", weeks=(1,)),
                ], "full")

                await sync_vuz.replace_vuz_groups(repo, part_groups, "part")
                await sync_vuz.replace_vuz_lessons(repo, [
                    vuz.VuzLesson("ЭК-23оз@vuz", 1, 1, "ANY", "Заочная",
                                  weeks=(1,)),
                ], "part")

                rows = (await db.execute(select(BaseLesson))).scalars().all()
                subjects = {r.subject for r in rows}
                assert subjects == {"Очная", "Заочная"}, (
                    f"одна форма снесла другую: {subjects}")
        finally:
            await env.close()
    run(scenario())


def test_resync_one_form_keeps_other():
    """Повторная загрузка очной не должна трогать очно-заочную."""
    async def scenario():
        env = await make_env()
        try:
            async with env.pool() as db:
                repo = RequestsRepo(db)
                await sync_vuz.replace_vuz_groups(
                    repo, [vuz.VuzGroup("ЭК-23@vuz", "FEU", 2, "full")], "full")
                await sync_vuz.replace_vuz_groups(
                    repo, [vuz.VuzGroup("ЭК-23оз@vuz", "FEU", 2, "part")], "part")
                await sync_vuz.replace_vuz_lessons(repo, [
                    vuz.VuzLesson("ЭК-23оз@vuz", 1, 1, "ANY", "Заочная",
                                  weeks=(1,)),
                ], "part")

                # Очную залили дважды — заочная должна остаться.
                for _ in range(2):
                    await sync_vuz.replace_vuz_lessons(repo, [
                        vuz.VuzLesson("ЭК-23@vuz", 1, 1, "ANY", "Очная",
                                      weeks=(1,)),
                    ], "full")

                rows = (await db.execute(select(BaseLesson))).scalars().all()
                assert {r.subject for r in rows} == {"Очная", "Заочная"}
        finally:
            await env.close()
    run(scenario())


# --- наложения пар -----------------------------------------------------------

def test_merge_para_clash_keeps_both_subjects():
    """Две пары на один номер — обе должны остаться видимыми.

    У вуза физкультура идёт потоком все недели, а иностранный язык —
    по подгруппам. На одной неделе они совпадают. В college_lesson ключ
    (дата, группа, пара) уникален, поэтому склеиваем через « / ».
    """
    from tgbot.services.schedule_layer import Slot
    from tgbot.services.sync_eios import _merge_para_clash

    merged = _merge_para_clash([
        Slot(7, "Физкультура", "Кабышева М.И."),
        Slot(7, "Иностранный", "Ольбик Н.И."),
    ])
    assert len(merged) == 1
    assert "Физкультура" in merged[0].subject
    assert "Иностранный" in merged[0].subject


def test_merge_para_clash_skips_duplicates():
    """Одна и та же пара дважды — не повод клеить «X / X»."""
    from tgbot.services.schedule_layer import Slot
    from tgbot.services.sync_eios import _merge_para_clash

    merged = _merge_para_clash([Slot(3, "Физика"), Slot(3, "Физика")])
    assert len(merged) == 1
    assert merged[0].subject == "Физика"


def test_merge_para_clash_keeps_distinct_paras():
    from tgbot.services.schedule_layer import Slot
    from tgbot.services.sync_eios import _merge_para_clash

    merged = _merge_para_clash([Slot(1, "А"), Slot(2, "Б"), Slot(3, "В")])
    assert [s.para for s in merged] == [1, 2, 3]


def test_materialize_does_not_crash_on_para_clash():
    """Материализация не должна падать на UNIQUE (дата, группа, пара)."""
    async def scenario():
        env = await make_env()
        try:
            async with env.pool() as db:
                repo = RequestsRepo(db)
                # Две пары на один слот: ровно то, что ломало вставку.
                # Недели РАЗНЫЕ, но пересекаются — как в реальном файле,
                # где физкультура идёт все недели, а иностранный только
                # по нечётным. Ключ (группа, чётность, день, пара, недели)
                # у них разный, поэтому обе попадают в базу.
                every = tuple(range(1, 53))
                odd = tuple(w for w in range(1, 53) if w % 2)
                await sync_vuz.replace_vuz_lessons(repo, [
                    vuz.VuzLesson("ЭК-23@vuz", 1, 7, "ANY", "Физкультура",
                                  "Кабышева М.И.", weeks=every),
                    vuz.VuzLesson("ЭК-23@vuz", 1, 7, "ANY", "Иностранный",
                                  "Ольбик Н.И.", weeks=odd),
                ], "full")
                from tgbot.services import sync_eios
                await sync_eios.materialize(repo, days=7)
                rows = (await db.execute(
                    select(CollegeLesson).where(
                        CollegeLesson.group == "ЭК-23@vuz",
                        CollegeLesson.para == 7))).scalars().all()
                assert rows, "пары не материализовались"
                assert all(" / " in r.subject or r.subject in ("Физкультура",
                                                              "Иностранный")
                           for r in rows)
        finally:
            await env.close()
    run(scenario())


def test_changes_of_both_forms_survive():
    """Замены одной формы не должны сносить замены другой.

    Тот же баг, что был с уроками: общий delete по source='vuz'
    оставлял только замены последнего загруженного файла.
    """
    async def scenario():
        env = await make_env()
        try:
            async with env.pool() as db:
                repo = RequestsRepo(db)
                await sync_vuz.replace_vuz_groups(
                    repo, [vuz.VuzGroup("ЭК-23@vuz", "FEU", 2, "full")], "full")
                await sync_vuz.replace_vuz_groups(
                    repo, [vuz.VuzGroup("ЭК-23оз@vuz", "FEU", 2, "part")], "part")

                await sync_vuz.replace_vuz_changes(repo, [
                    vuz.VuzChange("ЭК-23@vuz", datetime.date(2026, 11, 9), 1,
                                  "Очная замена"),
                ], "full")
                await sync_vuz.replace_vuz_changes(repo, [
                    vuz.VuzChange("ЭК-23оз@vuz", datetime.date(2026, 11, 9), 1,
                                  "Заочная замена"),
                ], "part")

                rows = (await db.execute(select(Substitution))).scalars().all()
                assert {r.subject for r in rows} == {"Очная замена", "Заочная замена"}
        finally:
            await env.close()
    run(scenario())
