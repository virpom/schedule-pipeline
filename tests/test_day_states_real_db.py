"""Все состояния экрана дня — на настоящей базе, не на заглушках.

Заглушки проверяют, что код вызвал нужную ветку. Здесь проверяется, что
ветка выбрана по реальным данным: пары в таблице, отметка публикации в
`schedule_file`, состояние источника в настройках.

Пять состояний, которые легко перепутать (и путали):

| Состояние | Признак |
|---|---|
| пары есть | строки в college_lesson |
| всё отменено | строки есть, у всех action = cancel |
| не опубликовано | пар нет, отметки в schedule_file нет, сайт жив |
| занятий нет | пар нет, отметка есть |
| не знаем | пар нет, отметки нет, сайт лежит |
"""
import asyncio
import datetime

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from common.schedule import SUB_CANCEL
from core import source_state
from core.day import DayView, build_day
from infrastructure.database.models import Base
from infrastructure.database.repo.requests import RequestsRepo


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


D = datetime.date(2026, 11, 9)      # понедельник


def _user(**kw):
    from types import SimpleNamespace
    base = dict(id=1, role="student", group="ДП-26", course=1,
                teacher_name=None, bell_detail="brief", send_image=True,
                subscribed=True, username=None, full_name="Тест")
    base.update(kw)
    return SimpleNamespace(**base)


async def _env(lessons=(), published=False, stale=False):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    pool = async_sessionmaker(engine, expire_on_commit=False)

    async def body(repo):
        if lessons:
            await repo.college_lessons.replace_date(D, list(lessons))
        if published:
            await repo.schedule_files.set_hash(D, "x")
        if stale:
            # Сайт «лежит»: последний успех давно в прошлом.
            await repo.settings.set(
                source_state.LAST_OK,
                (datetime.datetime.now() - datetime.timedelta(days=30)).isoformat())
        return await build_day(repo, _user(), D)

    async with pool() as db:
        view = await body(RequestsRepo(db))
    await engine.dispose()
    return view


def _lesson(para=1, action="", date=None):
    """Строка дня в том виде, в каком её принимает replace_date."""
    d = date or D
    return dict(date=d, group="ДП-26", para=para, para_end=para,
                subject="Математика", teacher="Иванов И.И.", room="101",
                source_url="", source="site", changed=False, action=action)


def test_lessons_state():
    view = run(_env(lessons=[_lesson()]))
    assert view.state == DayView.LESSONS
    assert len(view.lessons) == 1


def test_cancelled_state():
    """Все пары отменены — это не «занятий нет».

    Студент должен видеть зачёркнутые строки: иначе он решит, что пары
    просто не поставили, и придёт.
    """
    view = run(_env(lessons=[_lesson(action=SUB_CANCEL)]))
    assert view.state == DayView.CANCELLED
    assert len(view.lessons) == 1


def test_unverified_on_fresh_db():
    """Свежая база: ни разу не опрашивали — «не знаем», а не «не выложено».

    Это не мелочь: `is_stale` на пустой настройке считает источник
    неопробованным, и утверждать «расписание не выложено» нельзя.
    """
    view = run(_env())
    assert view.state == DayView.UNVERIFIED


def test_not_published_state():
    """Пар нет, отметки нет, но сайт опрашивался успешно — не выложили."""
    async def body():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        pool = async_sessionmaker(engine, expire_on_commit=False)
        async with pool() as db:
            repo = RequestsRepo(db)
            # Сайт жив: последний успех только что.
            await repo.settings.set(source_state.LAST_OK,
                                    datetime.datetime.now().isoformat())
            view = await build_day(repo, _user(), D)
        await engine.dispose()
        return view

    view = run(body())
    assert view.state == DayView.NOT_PUBLISHED


def test_no_lessons_state():
    """День опубликован, пар нет — занятий действительно нет."""
    view = run(_env(published=True))
    assert view.state == DayView.NO_LESSONS


def test_unverified_state():
    """Ни пар, ни публикации, ни связи с сайтом — утверждать нечего."""
    view = run(_env(stale=True))
    assert view.state == DayView.UNVERIFIED


def test_no_identity_state():
    """Без группы состояние даже не считается — сразу «выбери группу»."""
    async def body():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        pool = async_sessionmaker(engine, expire_on_commit=False)
        async with pool() as db:
            view = await build_day(RequestsRepo(db), _user(group=None), D)
        await engine.dispose()
        return view

    view = run(body())
    assert view.state == DayView.NO_IDENTITY
    assert view.identity_missing is True


def test_nearest_found_when_empty():
    """Пустой день — «Ближайшее» подсказывает, когда пары будут."""
    async def body():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        pool = async_sessionmaker(engine, expire_on_commit=False)
        async with pool() as db:
            repo = RequestsRepo(db)
            later = D + datetime.timedelta(days=2)
            await repo.college_lessons.replace_date(later, [_lesson(
                date=later, action="") | {"subject": "Физика",
                                          "teacher": "Петров П.П."}])
            view = await build_day(repo, _user(), D)
        await engine.dispose()
        return view

    view = run(body())
    assert view.nearest is not None
    assert view.nearest[0] == D + datetime.timedelta(days=2)
    assert view.nearest[1][0].subject == "Физика"


def test_nearest_skips_cancelled_day():
    """День из одних отмен «ближайшим» не считается: туда идти незачем."""
    async def body():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        pool = async_sessionmaker(engine, expire_on_commit=False)
        async with pool() as db:
            repo = RequestsRepo(db)
            cancel_day = D + datetime.timedelta(days=1)
            await repo.college_lessons.replace_date(cancel_day, [_lesson(
                date=cancel_day, action=SUB_CANCEL)])
            real_day = D + datetime.timedelta(days=3)
            await repo.college_lessons.replace_date(real_day, [_lesson(
                date=real_day, action="") | {"subject": "Настоящая",
                                             "teacher": "Петров П.П."}])
            view = await build_day(repo, _user(), D)
        await engine.dispose()
        return view

    view = run(body())
    assert view.nearest[0] == D + datetime.timedelta(days=3)
    assert view.nearest[1][0].subject == "Настоящая"
