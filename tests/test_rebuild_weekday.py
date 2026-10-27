"""Правка базы пересобирает два дня, а не все четырнадцать.

План 008. Правка базы действует на конкретный weekday и чётность, но
`_rebuild` без аргументов пересобирал всё окно: 1806 вызовов
`get_day_slots` и блокировка бота на 3.6 с.

Замерено на проде 27.10.2026:
    materialize()      — 3.62 с
    materialize_day()  — 0.33 с
Разница в 11 раз. Пока идёт пересборка, любая запись из другого
обработчика ждёт: middleware пишет `users` на каждое событие.

Окно 14 дней даёт ровно два дня с нужным weekday и чётностью.
"""
import datetime
import inspect


from common.schedule import PARITY_ANY
from tgbot.handlers import editor
from tgbot.services import sync_eios


def test_rebuild_accepts_weekday():
    sig = inspect.signature(editor._rebuild)
    assert "weekday" in sig.parameters
    assert "parity" in sig.parameters


def test_rebuild_uses_weekday_branch():
    src = inspect.getsource(editor._rebuild)
    assert "materialize_weekday" in src, "нет узкой пересборки"


def test_date_branch_wins():
    """Правка на дату по-прежнему пересобирает один день."""
    src = inspect.getsource(editor._rebuild)
    code = "\n".join(l.split("#", 1)[0] for l in src.splitlines())
    assert code.find("date is not None") < code.find("materialize_weekday")


def test_base_edits_pass_weekday():
    """Правка базы, удаление и откат знают weekday — и передают его."""
    for fn in (editor._save_base,):
        src = inspect.getsource(fn)
        assert "weekday=weekday" in src, f"{fn.__name__} пересобирает всё окно"
    src = inspect.getsource(editor.cb_undo)
    assert "weekday=weekday" in src, "откат пересобирает всё окно"


def test_materialize_weekday_exists():
    assert hasattr(sync_eios, "materialize_weekday")


def test_weekday_filters_days():
    """Из 14 дней остаются только нужные."""
    import asyncio

    calls = []

    async def fake_day(repo, date):
        calls.append(date)
        return 1

    real = sync_eios.materialize_day
    sync_eios.materialize_day = fake_day
    try:
        n = asyncio.run(sync_eios.materialize_weekday(None, weekday=2, parity=None))
    finally:
        sync_eios.materialize_day = real

    today = datetime.date.today()
    expected = [today + datetime.timedelta(days=d) for d in range(14)
                if (today + datetime.timedelta(days=d)).isoweekday() == 2]
    assert calls == expected
    assert n == len(expected)


def test_parity_any_does_not_filter():
    """ANY — «каждая неделя», фильтровать нечего."""
    import asyncio

    calls = []

    async def fake_day(repo, date):
        calls.append(date)

    real = sync_eios.materialize_day
    sync_eios.materialize_day = fake_day
    try:
        asyncio.run(sync_eios.materialize_weekday(None, weekday=2, parity=PARITY_ANY))
    finally:
        sync_eios.materialize_day = real

    today = datetime.date.today()
    expected = [today + datetime.timedelta(days=d) for d in range(14)
                if (today + datetime.timedelta(days=d)).isoweekday() == 2]
    assert len(calls) == len(expected), "ANY отсёк дни"


def test_parity_filters_by_college_parity():
    """Чётность считается со сдвигом колледжа, не по ISO."""
    import asyncio

    from tgbot.services.schedule_layer import PARITY_OFFSET, week_parity

    calls = []

    async def fake_day(repo, date):
        calls.append(date)

    real = sync_eios.materialize_day
    sync_eios.materialize_day = fake_day
    try:
        asyncio.run(sync_eios.materialize_weekday(None, weekday=2, parity="ODD"))
    finally:
        sync_eios.materialize_day = real

    today = datetime.date.today()
    expected = [today + datetime.timedelta(days=d) for d in range(14)
                if (today + datetime.timedelta(days=d)).isoweekday() == 2
                and week_parity(today + datetime.timedelta(days=d), PARITY_OFFSET) == "ODD"]
    assert calls == expected
