"""Тесты сборки дня из слоёв (сервисный уровень, на фейковом репо)."""
import asyncio
import datetime

from common.schedule import PARITY_ODD, SUB_ADD, SUB_CANCEL, SUB_REPLACE
from tgbot.services.schedule_layer import get_day_slots


class Row:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class FakeBase:
    def __init__(self, lessons):
        self._lessons = lessons

    async def get_day(self, group, weekday, parity, week=None):
        return [l for l in self._lessons
                if l.weekday == weekday and l.week_parity in (parity, "ANY")]


class FakeSubs:
    def __init__(self, subs):
        self._subs = subs

    async def get_for_date(self, group, date):
        return [s for s in self._subs if s.date == date]


class FakeRepo:
    def __init__(self, lessons=(), subs=()):
        self.base_lessons = FakeBase(list(lessons))
        self.substitutions = FakeSubs(list(subs))


def lesson(para, subject, weekday=3, parity=PARITY_ODD, teacher="", room=""):
    return Row(para=para, subject=subject, weekday=weekday, week_parity=parity,
               teacher=teacher, room=room)


def sub(para, date, action, subject="", teacher="", room="", comment=""):
    return Row(para=para, date=date, action=action, subject=subject,
               teacher=teacher, room=room, comment=comment)


def day(repo, group="ДП-26", date=None):
    """Слоты дня по ISO-чётности (тесты проверяют логику, не сдвиг колледжа)."""
    return asyncio.run(get_day_slots(repo, group, date, 0))


# 2026-10-21 — среда, ISO-неделя 43 (нечётная)
WED_ODD = datetime.date(2026, 10, 21)
WED_EVEN = datetime.date(2026, 10, 14)   # среда, неделя 42 (чётная)


def test_base_only():
    repo = FakeRepo([lesson(1, "Математика"), lesson(2, "Физика")])
    slots = day(repo, date=WED_ODD)
    assert [(s.para, s.subject) for s in slots] == [(1, "Математика"), (2, "Физика")]
    assert all(not s.changed for s in slots)


def test_parity_filters_out_other_week():
    """Нечётная база не должна показываться в чётную неделю."""
    repo = FakeRepo([lesson(1, "Математика", parity=PARITY_ODD)])
    slots = day(repo, date=WED_EVEN)
    assert slots == []


def test_replace_marks_changed():
    repo = FakeRepo([lesson(1, "Математика")],
                    [sub(1, WED_ODD, SUB_REPLACE, "Химия", "Сидоров С.С.")])
    slots = day(repo, date=WED_ODD)
    assert len(slots) == 1
    assert slots[0].subject == "Химия"
    assert slots[0].changed is True
    assert slots[0].teacher == "Сидоров С.С."


def test_cancel_keeps_slot_marked():
    """Отменённая пара остаётся в списке с action='cancel'.

    Раньше она выбрасывалась, и студент видел «Занятий нет» на месте
    отменённой пары — будто её никогда не было.
    """
    repo = FakeRepo([lesson(1, "Математика"), lesson(2, "Физика")],
                    [sub(1, WED_ODD, SUB_CANCEL)])
    slots = day(repo, date=WED_ODD)
    assert [(s.para, s.subject, s.action) for s in slots] == [
        (1, "Математика", SUB_CANCEL), (2, "Физика", "")]


def test_add_inserts_without_base():
    repo = FakeRepo([], [sub(3, WED_ODD, SUB_ADD, "История")])
    slots = day(repo, date=WED_ODD)
    assert [(s.para, s.subject, s.changed) for s in slots] == [(3, "История", True)]


def test_cancel_all_shows_cancelled_slots():
    """Все пары отменены — список не пустой, а из отменённых."""
    repo = FakeRepo([lesson(1, "Математика")], [sub(1, WED_ODD, SUB_CANCEL)])
    slots = day(repo, date=WED_ODD)
    assert [(s.para, s.action) for s in slots] == [(1, SUB_CANCEL)]


def test_slots_sorted_by_para():
    repo = FakeRepo([lesson(3, "Третья"), lesson(1, "Первая")],
                    [sub(2, WED_ODD, SUB_ADD, "Вторая")])
    slots = day(repo, date=WED_ODD)
    assert [s.para for s in slots] == [1, 2, 3]


def test_other_date_substitution_ignored():
    other = datetime.date(2026, 10, 22)
    repo = FakeRepo([lesson(1, "Математика")], [sub(1, other, SUB_REPLACE, "Химия")])
    slots = day(repo, date=WED_ODD)
    assert slots[0].subject == "Математика"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok  {name}")
    print("OK")


def test_add_over_existing_base_does_not_duplicate():
    """«Добавить» на пару, которая уже есть в базе, не должен давать два слота.

    Так бывает, когда замена помечена как add, хотя базовая пара существует
    (например, ПРк-25 в субботу).
    """
    repo = FakeRepo([lesson(1, "Геология")], [sub(1, WED_ODD, SUB_ADD, "Электротехника")])
    slots = day(repo, date=WED_ODD)
    assert len(slots) == 1
    assert slots[0].para == 1
    assert slots[0].subject == "Электротехника"
    assert slots[0].changed is True


def test_no_duplicate_paras_ever():
    """Номер пары в итоговом дне не должен повторяться ни при каких заменах."""
    repo = FakeRepo(
        [lesson(1, "А"), lesson(2, "Б"), lesson(3, "В")],
        [sub(1, WED_ODD, SUB_ADD, "X"), sub(2, WED_ODD, SUB_REPLACE, "Y"),
         sub(3, WED_ODD, SUB_CANCEL)],
    )
    slots = day(repo, date=WED_ODD)
    assert len(slots) == len({s.para for s in slots})


def test_default_offset_is_college_parity():
    """По умолчанию берётся чётность колледжа, а не ISO.

    Регрессия: хендлеры старосты вызывали get_day_slots() без аргумента и
    показывали не ту неделю — на 26.10.2026 (нечётная у колледжа) пропадала
    пара, стоящая только на нечётной неделе.
    """
    from tgbot.services.schedule_layer import PARITY_OFFSET

    assert PARITY_OFFSET == 1
    # 26.10.2026 — ISO-неделя 44 (чётная), у колледжа нечётная.
    d = datetime.date(2026, 10, 26)
    repo = FakeRepo([lesson(1, "Только нечётная", weekday=1, parity=PARITY_ODD)])
    slots = asyncio.run(get_day_slots(repo, "ДП-26", d))
    assert [s.para for s in slots] == [1], "пара нечётной недели должна быть видна"


def test_replace_without_base_lesson_is_shown():
    """Замена на пару, которой нет в базовом расписании, должна быть видна.

    У вуза такие часты: перенос на субботу, разовая консультация.
    Раньше учитывался только action='add', и замена молча пропадала —
    студент видел пустой день, хотя пара есть.
    """
    from tgbot.services.schedule_layer import get_day_slots

    async def scenario():
        import datetime as dt
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
        from infrastructure.database.models import Base
        from infrastructure.database.repo.requests import RequestsRepo

        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        pool = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with pool() as db:
                repo = RequestsRepo(db)
                date = dt.date(2026, 11, 7)
                # Базовой пары нет — только замена.
                await repo.substitutions.set(
                    date=date, group="ЭК-23@vuz", para=3,
                    action="replace", subject="Перенос", source="vuz")
                slots = await get_day_slots(repo, "ЭК-23@vuz", date)
                assert [s.para for s in slots] == [3]
                assert slots[0].subject == "Перенос"
                assert slots[0].changed
        finally:
            await engine.dispose()

    asyncio.get_event_loop_policy().new_event_loop().run_until_complete(scenario())
