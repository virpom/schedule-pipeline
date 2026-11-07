"""Состояния дня, которых НЕТ в боевых данных.

Проверка на живой базе показала, какие комбинации реально встречаются
(4704 случая, 07.11.2026):

| состояние | есть предупреждение | есть «Ближайшее» | сколько |
|---|---|---|---|
| lessons | нет | нет | 3465 |
| no_lessons | нет | да | 1065 |
| no_identity | нет | нет | 112 |
| cancelled | нет | да | 32 |
| no_lessons | нет | нет | 30 |

То есть золотые строки покрывают 4 состояния из 6 и НИ ОДНОЙ
комбинации с предупреждением о свежести. Именно там и живут ошибки:
`unverified` и `not_published` на проде не встретились, а сломанный
сайт — обычное дело.

Эти тесты закрывают пробел: собирают ветки руками, на настоящей базе.
"""
import asyncio
import datetime

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from common.schedule import SUB_CANCEL
from core import source_state
from core.day import DayView, build_day
from core.render import render_day
from infrastructure.database.models import Base
from infrastructure.database.repo.requests import RequestsRepo

D = datetime.date(2026, 11, 9)


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def _user(**kw):
    from types import SimpleNamespace
    base = dict(id=1, role="student", group="ДП-26", course=1,
                teacher_name=None, bell_detail="brief", send_image=True,
                subscribed=True)
    base.update(kw)
    return SimpleNamespace(**base)


async def _env(*, lessons=(), published=False, stale_minutes=None,
               extra_days=()):
    """База с заданным состоянием источника и содержимым дней."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    pool = async_sessionmaker(engine, expire_on_commit=False)

    async def body(repo):
        if lessons:
            await repo.college_lessons.replace_date(D, list(lessons))
        if published:
            await repo.schedule_files.set_hash(D, "x")
        if stale_minutes is not None:
            when = datetime.datetime.now() - datetime.timedelta(
                minutes=stale_minutes)
            await repo.settings.set(source_state.LAST_OK, when.isoformat())
        for offset, rows in extra_days:
            d = D + datetime.timedelta(days=offset)
            await repo.college_lessons.replace_date(d, list(rows))
        view = await build_day(repo, _user(), D)
        bell, lunches = await repo.bell_schedule.get_context()
        text = render_day(view, bell=bell, lunches=lunches, detail="brief",
                          is_teacher=False)
        return view, text

    async with pool() as db:
        out = await body(RequestsRepo(db))
    await engine.dispose()
    return out


def _lesson(action="", subject="Математика"):
    return dict(date=D, group="ДП-26", para=1, para_end=1, subject=subject,
                teacher="Иванов И.И.", room="101", source_url="",
                source="site", changed=False, action=action)


def test_lessons_with_stale_warning():
    """Пары есть, но сайт лежит — показываем пары И предупреждение.

    На проде эта комбинация не встретилась ни разу: сайт лежал, но
    подписчики с парами в этот момент не попали в выборку.
    """
    view, text = run(_env(lessons=[_lesson()], stale_minutes=120))
    assert view.state == DayView.LESSONS
    assert view.stale_when is not None
    assert "Математика" in text, "расписание скрылось из-за сбоя сайта"
    assert "Последняя успешная проверка" in text


def test_no_lessons_with_stale_warning():
    """День опубликован, пар нет, сайт лежит — «занятий нет» + тревога."""
    view, text = run(_env(published=True, stale_minutes=120))
    assert view.state == DayView.NO_LESSONS
    assert view.stale_when is not None
    assert "Занятий нет" in text
    assert "Последняя успешная проверка" in text


def test_unverified_no_warning_when_never_synced():
    """Сайт ни разу не опрашивался — «не знаем», но без упрёка.

    format_unverified сам добавляет «ни разу не загрузилось», а
    отдельное предупреждение дублировало бы эту мысль.
    """
    view, text = run(_env())
    assert view.state == DayView.UNVERIFIED
    assert view.stale_when is None
    assert "ни разу не загрузилось" in text


def test_not_published_no_warning():
    """День не выложен, сайт жив — просто «не выложено», без тревоги."""
    view, text = run(_env(stale_minutes=0))
    assert view.state == DayView.NOT_PUBLISHED
    assert view.stale_when is None


def test_cancelled_with_stale_warning():
    """Все пары отменены и сайт лежит — зачёркнутые строки + тревога."""
    view, text = run(_env(lessons=[_lesson(action=SUB_CANCEL)],
                          stale_minutes=120))
    assert view.state == DayView.CANCELLED
    assert view.stale_when is not None
    assert "Последняя успешная проверка" in text


def test_cancelled_no_nearest_when_all_cancelled():
    """Отменённый день не считается «ближайшим»: туда идти незачем."""
    cancelled = [_lesson(action=SUB_CANCEL)]
    real = dict(_lesson(), date=D + datetime.timedelta(days=1),
                subject="Настоящая")
    view, _ = run(_env(lessons=cancelled, extra_days=[(1, [real])]))
    assert view.state == DayView.CANCELLED
    assert view.nearest is not None
    assert view.nearest[1][0].subject == "Настоящая"


def test_teacher_only_vuz_gets_vuz_warning():
    """Преподаватель только вуза не должен получать тревогу колледжа.

    is_vuz(None) == False, и без отдельной проверки он видел чужую
    проблему: сайт колледжа лежит, а у него всё в порядке.
    """
    async def body():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        pool = async_sessionmaker(engine, expire_on_commit=False)
        async with pool() as db:
            repo = RequestsRepo(db)
            # Вуз «лежит», колледж — нет.
            await repo.settings.set(
                source_state.LAST_OK, datetime.datetime.now().isoformat())
            await repo.settings.set(
                source_state.LAST_OK_VUZ,
                (datetime.datetime.now() - datetime.timedelta(hours=5)).isoformat())
            vuz_group = "СА-26@vuz"
            await repo.college_lessons.replace_date(D, [dict(
                _lesson(), group=vuz_group, teacher="Кабышева М.И.")])
            view = await build_day(
                repo, _user(role="teacher", group=None,
                            teacher_name="Кабышева М.И."), D)
        await engine.dispose()
        return view

    view = run(body())
    assert view.state == DayView.LESSONS
    assert view.stale_when is not None, "тревога вуза не показана"
