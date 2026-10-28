"""«вакансия» — не преподаватель (план 097).

Пустая ставка записана словом прямо в поле преподавателя. На проде:
4 строки в base_lesson и 8 в college_lesson, все со значением
«вакансия».

_clean_teacher_names фильтровал пустые имена, но слово «вакансия»
непустое — оно проходило, попадало в список под буквой «В», и студент,
нажавший его, становился «преподавателем вакансии»: cb_teacher зовёт
set_role(user.id, "teacher") без единой проверки.
"""
import asyncio
import datetime

import pytest

from infrastructure.database.repo.college_lesson import _clean_teacher_names


@pytest.mark.parametrize("word", ["вакансия", "Вакансия", "ВАКАНСИЯ ",
                                  "вакансия.", "нет преподавателя"])
def test_vacancy_dropped(word):
    assert _clean_teacher_names([word, "Иванов И.И."]) == ["Иванов И.И."], word


def test_real_names_kept():
    got = _clean_teacher_names(["Иванов И.И.", "Кулян Р.А", "Усманов А.А."])
    assert "Иванов И.И." in got
    assert "Кулян Р.А" in got
    assert "Усманов А.А." in got


def test_only_vacancy_gives_empty():
    assert _clean_teacher_names(["вакансия"]) == []


def test_teacher_list_from_db_skips_vacancy(tmp_path):
    async def body():
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
        from infrastructure.database.models import Base
        from infrastructure.database.repo.requests import RequestsRepo
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/db.sqlite")
        async with engine.begin() as c:
            await c.run_sync(Base.metadata.create_all)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as sess:
                repo = RequestsRepo(sess)
                await repo.college_lessons.bulk_insert([
                    {"date": datetime.date(2026, 11, 9), "group": "ПРф-23",
                     "para": 2, "para_end": 2, "subject": "Геология",
                     "teacher": "вакансия", "room": "", "source_url": "",
                     "source": "base", "changed": False, "action": "",
                     "time_note": ""},
                    {"date": datetime.date(2026, 11, 9), "group": "ПРф-23",
                     "para": 3, "para_end": 3, "subject": "Монтаж",
                     "teacher": "Усманов А.А.", "room": "", "source_url": "",
                     "source": "base", "changed": False, "action": "",
                     "time_note": ""},
                ])
                got = await repo.college_lessons.get_teachers()
                assert "вакансия" not in [g.lower() for g in got], got
                assert "Усманов А.А." in got, got
        finally:
            await engine.dispose()

    asyncio.run(body())


def test_schedule_row_kept(tmp_path):
    """Строка расписания с «вакансия» не исчезает — фильтр только в списке."""
    async def body():
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
        from infrastructure.database.models import Base
        from infrastructure.database.repo.requests import RequestsRepo
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/db.sqlite")
        async with engine.begin() as c:
            await c.run_sync(Base.metadata.create_all)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as sess:
                repo = RequestsRepo(sess)
                await repo.base_lessons.upsert("ПРф-23", "ODD", 2, 2,
                                               "Геология", teacher="вакансия")
                lessons = await repo.base_lessons.get_week("ПРф-23", "ODD")
                assert any(l.subject == "Геология" for l in lessons), lessons
        finally:
            await engine.dispose()

    asyncio.run(body())
