"""Фундамент под вуз: суффикс группы, звонки, разделение источников.

Главная проверка здесь — что вуз не ломает колледж. Остальное появится
на следующих этапах.
"""
import datetime

from tests.test_schedule_layer_service import Row
from common.schedule import (VUZ_GROUP, course_from_group,
                             course_group_from_group, is_vuz, strip_unit)


def test_college_group_is_not_vuz():
    assert not is_vuz("ЭК-23")
    assert not is_vuz("ДП-26ФП")
    assert not is_vuz(None)
    assert not is_vuz("")


def test_vuz_group_is_recognised():
    assert is_vuz("ЭК-23@vuz")
    assert is_vuz("ГП-26з@vuz")


def test_suffix_stripped_for_display():
    """Студент должен видеть ЭК-23, а не ЭК-23@vuz."""
    assert strip_unit("ЭК-23@vuz") == "ЭК-23"
    assert strip_unit("ЭК-23") == "ЭК-23"
    assert strip_unit(None) is None


def test_same_name_differs_by_suffix():
    """Коллизия реальна: ЭК-23 есть и в колледже, и в вузе — разные люди."""
    college = "ЭК-23"
    vuz = "ЭК-23@vuz"
    assert college != vuz
    assert strip_unit(college) == strip_unit(vuz)


def test_course_parsing_survives_suffix():
    """course_from_group ищет двузначное число — суффикс ему не мешает."""
    assert course_from_group("ЭК-23@vuz") == course_from_group("ЭК-23")


def test_vuz_gets_own_bell_group():
    """У вуза 8 пар и своя сетка — деление по курсам ему не подходит."""
    assert course_group_from_group("ЭК-23@vuz") == VUZ_GROUP


def test_college_keeps_course_based_bells():
    for group in ("ДП-26", "ЭК-23", "ТЭ-24"):
        assert course_group_from_group(group) in ("I_IV", "II_III")


def test_vuz_bells_cover_eight_paras():
    """Сетка вуза: восемь пар, последняя заканчивается в 22:00."""
    import importlib.util
    import pathlib

    path = pathlib.Path(__file__).parent.parent / "migrations" / "versions" / "0004_vuz.py"
    spec = importlib.util.spec_from_file_location("mig0004", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    paras = [row[0] for row in mod.VUZ_BELLS]
    assert paras == [1, 2, 3, 4, 5, 6, 7, 8]
    assert mod.VUZ_BELLS[0][1] == "08:40"
    assert mod.VUZ_BELLS[-1][4] == "22:00"


def test_vuz_bell_times_do_not_overlap():
    """Пары идут подряд: конец одной раньше начала следующей."""
    import importlib.util
    import pathlib

    path = pathlib.Path(__file__).parent.parent / "migrations" / "versions" / "0004_vuz.py"
    spec = importlib.util.spec_from_file_location("mig0004b", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    def t(v):
        return datetime.time.fromisoformat(v)

    for (_, *a), (_, *b) in zip(mod.VUZ_BELLS, mod.VUZ_BELLS[1:]):
        assert t(a[3]) < t(b[0]), f"пара пересекается: {a} и {b}"


def test_replace_bells_keeps_vuz_rows():
    """Мина: replace_bells удалял всё, кроме ALL, — звонки вуза исчезали.

    Первый же проход колледжа сносил бы сетку вуза. Проверяем на
    настоящей in-memory SQLite, потому что тут важен сам SQL-запрос.
    """
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from infrastructure.database.models import Base, BellSchedule
    from infrastructure.database.repo.requests import RequestsRepo
    from tgbot.services.sync_eios import replace_bells

    async def run():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        pool = async_sessionmaker(engine, expire_on_commit=False)

        t = datetime.time
        async with pool() as db:
            repo = RequestsRepo(db)
            # чужие строки, которые обязаны выжить
            db.add_all([
                BellSchedule(day_type="MONDAY", course_group="ALL", para=0,
                             start=t(8, 0), h1_end=t(8, 15), h2_start=t(8, 20), end=t(8, 30)),
                BellSchedule(day_type="OTHER", course_group="VUZ", para=1,
                             start=t(8, 40), h1_end=t(9, 25), h2_start=t(9, 35), end=t(10, 10)),
                # своя старая строка колледжа — её перезаписать можно
                BellSchedule(day_type="OTHER", course_group="I_IV", para=1,
                             start=t(9, 0), h1_end=t(9, 45), h2_start=t(9, 55), end=t(10, 30)),
            ])
            await db.commit()

            slot = Row(day_type="OTHER", course_group="II_III", para=1,
                       start=t(11, 0), end1=t(11, 45), start2=t(11, 55), end2=t(12, 30))
            await replace_bells(repo, [slot])

        async with pool() as db:
            rows = (await db.execute(
                __import__("sqlalchemy").select(BellSchedule)
            )).scalars().all()
            kept = {(r.course_group, r.para) for r in rows}
        await engine.dispose()
        return kept

    kept = asyncio.run(run())
    # С плана 033 «Разговоры о важном» приходят из файла звонков, а не
    # из константы. Значит старая строка ALL должна уступить новой —
    # иначе вставка падает на UNIQUE (day_type, course_group, para).
    # В этом вызове слота ALL нет, поэтому её и не остаётся.
    assert ("ALL", 0) not in kept, \
        "старая константа ALL переживает замену и ломает вставку"
    assert ("VUZ", 1) in kept, "звонки вуза не должны пропасть"
    assert ("II_III", 1) in kept, "новые звонки колледжа должны появиться"
    assert ("I_IV", 1) not in kept, "старые звонки колледжа перезаписываются"
