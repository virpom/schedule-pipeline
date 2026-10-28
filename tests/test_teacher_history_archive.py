"""История преподавателя берётся из архива (план 082).

План 082 предлагал засыпать прошлое в materialize. Проверка показала,
что это не тот путь: с раунда 199 прошлые дни ежедневно удаляются из
college_lesson, и засыпка воскресила бы их, снова раздув таблицу.

Студент историю получал: _hist_page подмешивает даты из day_snapshot.
У преподавателя такой ветки не было, и история была пуста у всех трёх
на проде: 0 прошедших дат при 8–10 будущих.
"""
import inspect

from tgbot.handlers import user as user_mod


def test_teacher_branch_uses_snapshot():
    body = inspect.getsource(user_mod._hist_page)
    assert "get_dates_for_teacher" in body
    assert "snapshots" in body, "преподаватель не смотрит в архив"


def test_student_branch_still_uses_snapshot():
    body = inspect.getsource(user_mod._hist_page)
    assert "get_dates_for_group" in body


def test_teacher_day_falls_back_to_archive():
    body = inspect.getsource(user_mod.cb_hist_date)
    assert "_teacher_snapshot_lessons" in body


def test_archive_has_teacher_methods():
    from infrastructure.database.repo.day_snapshot import DaySnapshotRepo
    assert hasattr(DaySnapshotRepo, "get_dates_for_teacher")
    assert hasattr(DaySnapshotRepo, "get_groups")


def test_teacher_dates_filters_by_surname():
    """Архив пишется по группам — нужен поиск по фамилии."""
    from infrastructure.database.repo.day_snapshot import DaySnapshotRepo
    body = inspect.getsource(DaySnapshotRepo.get_dates_for_teacher)
    assert "payload" in body
    assert "surname" in body


def test_teacher_snapshot_lessons_filters():
    body = inspect.getsource(user_mod._teacher_snapshot_lessons)
    assert 'getattr(item, "teacher", "")' in body


def test_empty_name_safe():
    """Роль teacher без фамилии не должна падать."""
    body = inspect.getsource(user_mod._teacher_snapshot_lessons)
    assert "user.teacher_name else" in body


# --- поведение на настоящей SQLite ------------------------------------------

def test_teacher_dates_from_archive(tmp_path):
    """Снимок группы с парой преподавателя даёт дату в истории."""
    import asyncio
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from infrastructure.database.models import Base
    from infrastructure.database.repo.requests import RequestsRepo

    async def body():
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/db.sqlite")
        async with engine.begin() as c:
            await c.run_sync(Base.metadata.create_all)
        sf = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with sf() as sess:
                repo = RequestsRepo(sess)
                d = __import__("datetime").date.today() - __import__("datetime").timedelta(days=3)
                from types import SimpleNamespace
                await repo.snapshots.save(d, "ДП-26", [
                    SimpleNamespace(para=1, subject="История",
                                    teacher="Данилова А.Н.", room="5"),
                ])
                dates = await repo.snapshots.get_dates_for_teacher("Данилова")
                assert d in dates, f"архив не нашёл: {dates}"
                other = await repo.snapshots.get_dates_for_teacher("Несуществов")
                assert other == []
                groups = await repo.snapshots.get_groups(d)
                assert "ДП-26" in groups
        finally:
            await engine.dispose()

    asyncio.run(body())
