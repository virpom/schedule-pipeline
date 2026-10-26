"""Откат правки: журнал должен помнить все поля слота.

План 142. Два дефекта:

* `_save_base` писал в `old_value` только предмет, а `cb_undo`
  восстанавливает предмет, преподавателя и кабинет — откат молча стирал
  преподавателя у 100% пар (2659 из 2659);
* `_save_sub` не писал `old_value` вовсе, и откат замены просто удалял
  строку. Если поверх уже стояла замена, `set()` её перезаписал, и
  восстанавливать было нечего.

Здесь проверяется форма данных в журнале и восстановление из неё, без
телеги и хендлеров.
"""
import asyncio
import datetime as dt
import json

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from infrastructure.database.models import Base
from infrastructure.database.repo.requests import RequestsRepo


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


async def make_env():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def test_base_undo_restores_teacher_and_room():
    """Восстановление из журнала возвращает преподавателя и кабинет.

    Проверяем не хендлер, а сам контракт: то, что кладёт `_save_base` в
    `old_value`, должно быть достаточно для полного восстановления.
    """
    async def scenario():
        engine, pool = await make_env()
        try:
            async with pool() as db:
                repo = RequestsRepo(db)
                await repo.base_lessons.upsert(
                    "ДП-26", "EVEN", 3, 2, "История России",
                    teacher="Куранова Е.И.", room="201", source="site")

                old = await repo.base_lessons.get_day("ДП-26", 3, "EVEN")
                old_slot = next(l for l in old if l.para == 2)

                # Ровно то, что теперь пишет _save_base.
                old_value = {"subject": old_slot.subject,
                             "teacher": old_slot.teacher,
                             "room": old_slot.room}

                # Правим и «откатываем».
                await repo.base_lessons.upsert(
                    "ДП-26", "EVEN", 3, 2, "Другой предмет",
                    teacher="", room="", source="manual")
                restored = json.loads(json.dumps(old_value))
                await repo.base_lessons.upsert(
                    "ДП-26", "EVEN", 3, 2, restored["subject"],
                    teacher=restored.get("teacher", ""),
                    room=restored.get("room", ""),
                    source="manual", updated_by=1)

                after = await repo.base_lessons.get_day("ДП-26", 3, "EVEN")
                slot = next(l for l in after if l.para == 2)
                assert slot.subject == "История России"
                assert slot.teacher == "Куранова Е.И.", (
                    "откат стёр преподавателя — план 142"
                )
                assert slot.room == "201"
        finally:
            await engine.dispose()
    run(scenario())


def test_sub_undo_restores_previous_substitution():
    """Откат замены возвращает прежнюю замену, а не удаляет слот.

    Сценарий из плана: ставим А, потом Б на ту же пару. `set()` — upsert,
    поэтому А перезаписана. Раньше откат делал `delete()` и терял обе.
    """
    async def scenario():
        engine, pool = await make_env()
        try:
            async with pool() as db:
                repo = RequestsRepo(db)
                day = dt.date(2026, 10, 27)

                # Замена А.
                await repo.substitutions.set(
                    day, "ДП-26", 4, "replace", "Замена А",
                    teacher="Иванов И.И.", room="101", source="site")

                # Староста ставит Б — _save_sub сначала читает прежнюю.
                before = await repo.substitutions.get_for_date("ДП-26", day)
                old_sub = next((s for s in before if s.para == 4), None)
                assert old_sub is not None, "прежняя замена должна читаться"
                old_value = {"action": old_sub.action,
                             "subject": old_sub.subject,
                             "teacher": old_sub.teacher,
                             "room": old_sub.room}

                await repo.substitutions.set(
                    day, "ДП-26", 4, "replace", "Замена Б",
                    teacher="Петров П.П.", room="102", source="site")

                # Откат: восстанавливаем из журнала, а не удаляем.
                await repo.substitutions.set(
                    day, "ДП-26", 4, old_value["action"], old_value["subject"],
                    old_value["teacher"], old_value["room"], source="site")

                subs = await repo.substitutions.get_for_date("ДП-26", day)
                slot = next(s for s in subs if s.para == 4)
                assert slot.subject == "Замена А", (
                    "откат потерял предыдущую замену — план 142"
                )
                assert slot.teacher == "Иванов И.И."
        finally:
            await engine.dispose()
    run(scenario())


def test_sub_undo_without_previous_deletes():
    """Если замены до правки не было — откат снимает слот совсем.

    Это основной случай и он должен остаться прежним: удалили замену —
    снова видна базовая пара.
    """
    async def scenario():
        engine, pool = await make_env()
        try:
            async with pool() as db:
                repo = RequestsRepo(db)
                day = dt.date(2026, 10, 28)

                before = await repo.substitutions.get_for_date("ДП-26", day)
                old_sub = next((s for s in before if s.para == 4), None)
                assert old_sub is None

                await repo.substitutions.set(
                    day, "ДП-26", 4, "replace", "Новая", source="site")

                # old_value пуст -> delete.
                await repo.substitutions.delete(day, "ДП-26", 4)

                subs = await repo.substitutions.get_for_date("ДП-26", day)
                assert not any(s.para == 4 for s in subs)
        finally:
            await engine.dispose()
    run(scenario())


def test_journal_writes_full_slot():
    """`_save_base` и `cb_del_base` кладут в журнал все три поля.

    Проверяем исходник: если кто-то снова сузит old_value до subject,
    тест упадёт — иначе регрессия пройдёт незамеченной.
    """
    import inspect
    from tgbot.handlers import editor

    src = inspect.getsource(editor)
    # Два места: сохранение пары и удаление пары.
    assert src.count('"teacher": old_slot.teacher') == 2, (
        "old_value должен содержать teacher в обоих местах (план 142)"
    )
    assert src.count('"room": old_slot.room') == 2


def test_save_sub_reads_previous():
    """`_save_sub` читает прежнюю замену до upsert-а."""
    import inspect
    from tgbot.handlers import editor

    src = inspect.getsource(editor._save_sub)
    assert "get_for_date" in src, "прежняя замена не читается — план 142"
    assert "old_value=" in src, "old_value не пишется в журнал"
    # Читать надо ДО set, иначе получим уже перезаписанную строку.
    assert src.index("get_for_date") < src.index("substitutions.set"), (
        "прежнюю замену надо читать до set()"
    )


def test_undo_restores_sub_before_delete():
    """`cb_undo` для замены сначала пробует восстановить, потом удалить."""
    import inspect
    from tgbot.handlers import editor

    src = inspect.getsource(editor.cb_undo)
    assert "old.get(\"subject\")" in src
    assert "substitutions.set" in src, "восстановление замены отсутствует"
    # Ветка восстановления должна идти раньше удаления.
    assert src.index("substitutions.set") < src.index("substitutions.delete")
