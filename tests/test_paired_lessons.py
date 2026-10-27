"""Спаренные пары склеиваются в одно занятие.

План 056. В файле колледжа одна тема на два часа идёт двумя строками
подряд — 23 случая из 704. `materialize` жёстко писал
`"para_end": slot.para`, а `Slot` вообще не имел такого поля, поэтому
спаренность терялась.

Что видел студент (проверено на проде, ДП-26 суббота):

    1) 09:00–09:45 / 09:50–10:35  Организация документооборота
    2) 10:45–11:30 / 11:30–11:55 / 11:55–12:40  Организация документооборота

То есть одно занятие выглядело как два разных с перерывом между ними.
"""
import datetime
import inspect

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from infrastructure.database.models import Base
from infrastructure.database.repo.requests import RequestsRepo
from tgbot.services import sync_eios
from tgbot.services.schedule_layer import Slot, _join_paired, get_day_slots


def _slot(para, subject="Тема", teacher="Иванов И.И.", **kw):
    return Slot(para, subject, teacher, group=kw.pop("group", "ДП-26"), **kw)


def test_two_identical_lessons_join():
    out = _join_paired([_slot(1), _slot(2)])
    assert len(out) == 1
    assert out[0].para == 1
    assert out[0].para_end == 2


def test_three_in_a_row_join():
    out = _join_paired([_slot(1), _slot(2), _slot(3)])
    assert len(out) == 1
    assert out[0].para_end == 3


def test_different_subject_not_joined():
    out = _join_paired([_slot(1, "Математика"), _slot(2, "Физика")])
    assert len(out) == 2


def test_different_teacher_not_joined():
    out = _join_paired([_slot(1, teacher="Иванов И.И."),
                        _slot(2, teacher="Петров П.П.")])
    assert len(out) == 2


def test_gap_not_joined():
    """Пара через номер — не спаренная."""
    out = _join_paired([_slot(1), _slot(3)])
    assert len(out) == 2


def test_changed_not_joined():
    """Замену не склеиваем: у неё своя семантика."""
    out = _join_paired([_slot(1), _slot(2, changed=True, action="replace")])
    assert len(out) == 2


def test_single_lesson_keeps_para_end():
    out = _join_paired([_slot(3)])
    assert out[0].para_end == 3


def test_slot_has_para_end():
    """Поле есть и по умолчанию равно para."""
    assert Slot(5, "Тема").para_end == 5


def test_materialize_writes_real_para_end():
    """materialize больше не пишет slot.para жёстко."""
    src = inspect.getsource(sync_eios.materialize)
    assert '"para_end": slot.para,' not in src, \
        "спаренность снова теряется при материализации"
    assert "para_end" in src


def test_materialize_day_writes_real_para_end():
    src = inspect.getsource(sync_eios.materialize_day)
    assert '"para_end": slot.para,' not in src


@pytest.mark.asyncio
async def test_get_day_slots_joins_from_base():
    """Сквозная проверка: две строки в базе дают один слот."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    pool = async_sessionmaker(engine, expire_on_commit=False)
    async with pool() as db:
        repo = RequestsRepo(db)
        from infrastructure.database.models import BaseLesson

        day = datetime.date(2026, 11, 7)  # суббота
        for para in (1, 2):
            db.add(BaseLesson(
                group="ДП-26", week_parity="ANY", weekday=day.isoweekday(),
                para=para, subject="Организация документооборота",
                teacher="Харькова Д.А.", room="", source="site",
                time_note="", updated_at=datetime.datetime.now()))
        await db.commit()

        slots = await get_day_slots(repo, "ДП-26", day)
    await engine.dispose()

    target = [s for s in slots if s.subject.startswith("Организация")]
    assert len(target) == 1, f"не склеилось: {len(target)} слотов"
    assert target[0].para == 1
    assert target[0].para_end == 2
