"""Преподаватель вуза, пришедший через замену, находится поиском (096).

get_teachers_vuz брал имена только из base_lesson. Комментарий объяснял
это тем, что «пары вуза лежат в base_lesson, не в college_lesson» — но
college_lesson это материализованный base_lesson ПЛЮС замены. Кто ведёт
пару только по замене (заменил заболевшего), в base_lesson отсутствует
вовсе, и в списке не появлялся.

На проде таких трое: Кулян Р.А (ЭК-25@vuz), Маргаритова Р.С.
(ГП-25@vuz), Николаева Ю.А. (МЦ-22оз@vuz). Первые две проверены на
копии прода после правки — находятся; третью уже вычистила чистка по
датам, проверить нечем.
"""
import asyncio
import datetime


def _setup(tmp_path):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from infrastructure.database.models import Base
    from infrastructure.database.repo.requests import RequestsRepo
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/db.sqlite")
    return engine, async_sessionmaker(engine, expire_on_commit=False), RequestsRepo, Base


def test_substitution_teacher_listed(tmp_path):
    async def body():
        engine, sf, RequestsRepo, Base = _setup(tmp_path)
        async with engine.begin() as c:
            await c.run_sync(Base.metadata.create_all)
        try:
            async with sf() as sess:
                repo = RequestsRepo(sess)
                await repo.base_lessons.upsert("ЭК-25@vuz", "ODD", 2, 1,
                                               "Макроэкономика", teacher="Обычный О.О.")
                # Преподаватель только в materialized-слое.
                await repo.college_lessons.bulk_insert([{
                    "date": datetime.date(2026, 11, 9), "group": "ЭК-25@vuz", "para": 2,
                    "para_end": 2, "subject": "Макроэкономика",
                    "teacher": "Кулян Р.А", "room": "", "source_url": "",
                    "source": "sub", "changed": True, "action": "replace",
                    "time_note": "",
                }])
                got = await repo.college_lessons.get_teachers_vuz()
                assert "Кулян Р.А" in got, f"заменяющий не найден: {got}"
                assert "Обычный О.О." in got, "базовый преподаватель потерян"
        finally:
            await engine.dispose()

    asyncio.run(body())


def test_college_teachers_unaffected(tmp_path):
    """Колледжный список не задет: там своя функция."""
    async def body():
        engine, sf, RequestsRepo, Base = _setup(tmp_path)
        async with engine.begin() as c:
            await c.run_sync(Base.metadata.create_all)
        try:
            async with sf() as sess:
                repo = RequestsRepo(sess)
                await repo.base_lessons.upsert("ДП-26", "ODD", 2, 1,
                                               "История", teacher="Коленова В.А.")
                got = await repo.college_lessons.get_teachers_vuz()
                assert "Коленова В.А." not in got, got
        finally:
            await engine.dispose()

    asyncio.run(body())


def test_duplicates_collapsed(tmp_path):
    """Один человек в обоих слоях — одна запись."""
    async def body():
        engine, sf, RequestsRepo, Base = _setup(tmp_path)
        async with engine.begin() as c:
            await c.run_sync(Base.metadata.create_all)
        try:
            async with sf() as sess:
                repo = RequestsRepo(sess)
                await repo.base_lessons.upsert("ЭК-25@vuz", "ODD", 2, 1,
                                               "Макроэкономика", teacher="Кулян Р.А")
                await repo.college_lessons.bulk_insert([{
                    "date": datetime.date(2026, 11, 9), "group": "ЭК-25@vuz", "para": 2,
                    "para_end": 2, "subject": "Макроэкономика",
                    "teacher": "Кулян Р.А", "room": "", "source_url": "",
                    "source": "sub", "changed": True, "action": "replace",
                    "time_note": "",
                }])
                got = await repo.college_lessons.get_teachers_vuz()
                assert got.count("Кулян Р.А") == 1, got
        finally:
            await engine.dispose()

    asyncio.run(body())
