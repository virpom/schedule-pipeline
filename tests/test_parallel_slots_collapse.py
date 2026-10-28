"""Две пары на одном номере склеиваются в один слот (план 117).

base_lesson хранит параллельные подгруппы двумя строками с разными
наборами недель: физкультура идёт потоком, иностранный — по подгруппам
на том же слоте.

get_day_slots обе строки честно отдавал, _join_paired их не трогает (он
про пары подряд), и студент видел два блока «7)» подряд в одно время.
На проде так было у ИП-26-2@vuz и АП-24@vuz.

Проверено на копии прод-базы: после правки ИП-26-2 отдаёт 7 слотов
вместо 8, АП-24 — 5 вместо 6, дубля номера нет.
"""
import asyncio
import datetime

from tgbot.services.schedule_layer import _collapse_same_para
from tgbot.services.schedule_layer import Slot

D = datetime.date(2026, 10, 28)


def _slot(para, subject, teacher="", room="", para_end=None):
    s = Slot(para, subject, teacher, room)
    if para_end is not None:
        s.para_end = para_end
    return s


def test_same_para_merged():
    got = _collapse_same_para([
        _slot(7, "Физкультура", "Кабышева М.И."),
        _slot(7, "Иностранный", "Кострицына Н.А."),
    ])
    assert len(got) == 1, got
    assert got[0].subject == "Физкультура / Иностранный"
    assert got[0].teacher == "Кабышева М.И. / Кострицына Н.А."


def test_different_paras_untouched():
    got = _collapse_same_para([_slot(6, "Химия"), _slot(7, "Право")])
    assert len(got) == 2
    assert got[0].subject == "Химия"


def test_same_subject_not_doubled():
    """«Язык / Язык» не печатаем."""
    got = _collapse_same_para([_slot(7, "Язык", "И"), _slot(7, "Язык", "П")])
    assert len(got) == 2, got


def test_two_classes_kept():
    """Два преподавателя на тот же предмет — два слота (план 081)."""
    got = _collapse_same_para([
        _slot(7, "Физкультура", "Кабышева М.И."),
        _slot(7, "Физкультура", "Кострицына Н.А."),
    ])
    assert len(got) == 2, got


def test_rooms_joined():
    got = _collapse_same_para([_slot(7, "А", "И", "М-310"),
                               _slot(7, "Б", "П", "М-103")])
    assert got[0].room == "М-310 / М-103", got[0].room


def test_empty_subject_not_merged():
    got = _collapse_same_para([_slot(7, "Химия"), _slot(7, "")])
    assert len(got) == 2, got


def test_from_real_db_shape(tmp_path):
    """Полный путь: base_lesson с двумя строками → один слот."""
    async def body():
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
        from infrastructure.database.models import Base
        from infrastructure.database.repo.requests import RequestsRepo
        from tgbot.services.schedule_layer import get_day_slots
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/db.sqlite")
        async with engine.begin() as c:
            await c.run_sync(Base.metadata.create_all)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as sess:
                repo = RequestsRepo(sess)
                await repo.base_lessons.upsert("ИП-26-2@vuz", "ODD", 3, 7,
                                               "Физкультура", teacher="Кабышева М.И.",
                                               weeks="7,9,11,13")
                await repo.base_lessons.upsert("ИП-26-2@vuz", "ODD", 3, 7,
                                               "Иностранный", teacher="Кострицына Н.А.",
                                               weeks="6,7,8,9,10")
                slots = await get_day_slots(repo, "ИП-26-2@vuz", D)
                paras = [s.para for s in slots]
                assert paras == [7], f"дубль номера: {paras}"
                assert " / " in slots[0].subject, slots[0].subject
        finally:
            await engine.dispose()

    asyncio.run(body())
