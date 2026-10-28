"""Подсказки преподавателя при ручном вводе (план 091).

Ввод преподавателя был свободным текстом без единой подсказки: ни
get_teachers, ни get_teachers_vuz в editor.py не вызывались. Предмет
подсказки имел — при том что предметов у группы 10–31, а преподавателей
в базе 186. Опечатка в фамилии делает пару невидимой для поиска, и
староста этого не видит: он получает «Сохранено», а студент видит пару
без преподавателя.

Список по всей базе в кнопки не влезает, поэтому берём тех, кто ведёт
эту группу.

Ловушка, на которой сломался такой же механизм для предметов (план
073): _suggest_kb кладёт в callback_data индекс, а обработчик читает
список из FSM. Забыть state.update_data(suggestions=...) — и каждая
кнопка отвечает «Устарело». Копирую вместе с этим.
"""
import asyncio
import inspect

from tgbot.handlers import editor as editor_mod


def _repo(tmp_path):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from infrastructure.database.models import Base
    from infrastructure.database.repo.requests import RequestsRepo
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/db.sqlite")
    return engine, async_sessionmaker(engine, expire_on_commit=False), RequestsRepo, Base


def test_suggestions_from_group(tmp_path):
    async def body():
        engine, sf, RequestsRepo, Base = _repo(tmp_path)
        async with engine.begin() as c:
            await c.run_sync(Base.metadata.create_all)
        try:
            async with sf() as sess:
                repo = RequestsRepo(sess)
                await repo.base_lessons.upsert("ДП-26", "ODD", 2, 1,
                                               "История", teacher="Коленова В.А.")
                await repo.base_lessons.upsert("ДП-26", "ODD", 2, 2,
                                               "Право", teacher="Иванов И.И.")
                got = await editor_mod._teacher_suggestions(repo, "ДП-26")
                assert "Коленова В.А." in got, got
                assert "Иванов И.И." in got, got
        finally:
            await engine.dispose()

    asyncio.run(body())


def test_suggestions_normalized(tmp_path):
    """Две записи одного человека — одна кнопка (план 090)."""
    async def body():
        engine, sf, RequestsRepo, Base = _repo(tmp_path)
        async with engine.begin() as c:
            await c.run_sync(Base.metadata.create_all)
        try:
            async with sf() as sess:
                repo = RequestsRepo(sess)
                await repo.base_lessons.upsert("ДП-26", "ODD", 2, 1,
                                               "История", teacher="Кокошка И. П.")
                await repo.base_lessons.upsert("ДП-26", "ODD", 2, 2,
                                               "Право", teacher="Кокошка И.П.")
                got = await editor_mod._teacher_suggestions(repo, "ДП-26")
                assert got == ["Кокошка И.П."], got
        finally:
            await engine.dispose()

    asyncio.run(body())


def test_suggestions_scoped_to_group(tmp_path):
    """Чужой преподаватель в подсказках не появляется."""
    async def body():
        engine, sf, RequestsRepo, Base = _repo(tmp_path)
        async with engine.begin() as c:
            await c.run_sync(Base.metadata.create_all)
        try:
            async with sf() as sess:
                repo = RequestsRepo(sess)
                await repo.base_lessons.upsert("ДП-26", "ODD", 2, 1,
                                               "История", teacher="Коленова В.А.")
                await repo.base_lessons.upsert("ИС-25", "ODD", 2, 1,
                                               "Право", teacher="Чужой Ч.Ч.")
                got = await editor_mod._teacher_suggestions(repo, "ДП-26")
                assert "Чужой Ч.Ч." not in got, got
        finally:
            await engine.dispose()

    asyncio.run(body())


def test_suggestions_stored_in_state():
    """Без этого кнопки отвечают «Устарело» — ловушка плана 073."""
    for fn in (editor_mod.cb_subject_suggestion, editor_mod.cb_sub_subject_suggestion,
               editor_mod.on_subject):
        body = inspect.getsource(fn)
        assert "suggestions=tsug" in body, fn.__name__


def test_suggestion_handler_reads_state():
    body = inspect.getsource(editor_mod.cb_teacher_suggestion)
    assert 'data.get("suggestions")' in body


def test_keyboard_has_skip_and_back():
    body = inspect.getsource(editor_mod._teacher_kb)
    assert "Пропустить" in body and "Назад" in body


def test_all_three_entry_points_use_suggestions():
    for fn in (editor_mod.cb_subject_suggestion, editor_mod.cb_sub_subject_suggestion,
               editor_mod.on_subject):
        body = inspect.getsource(fn)
        assert "_teacher_suggestions" in body, fn.__name__
        assert "_skip_kb(\"ed:skip_teacher\")" not in body, fn.__name__


def test_manual_input_still_works():
    """Свободный текст остаётся: подсказки — дополнение, не замена."""
    body = inspect.getsource(editor_mod.on_teacher)
    assert "message.text" in body
