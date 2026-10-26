"""Откат доходит до студента, а провал пересборки не выглядит успехом.

План 004. `cb_undo` менял слои, но не пересобирал `college_lesson`.
Студент читает именно её, а не слои, поэтому откат доезжал до него
только через следующий проход поллера — до пяти минут, а если сайт лежал,
то никогда. Староста при этом видел «Откачено».

План 009. `_rebuild` глотал любое исключение и возвращал None, а
обработчик продолжал отвечать «✅ Сохранено». Если `materialize` упал
(заблокирована БД, нарушен UNIQUE, кончилось место), студент видел старое
расписание, а староста — подтверждение успеха.
"""
import inspect

from tgbot.handlers import editor


def test_undo_rebuilds_college_lesson():
    """`cb_undo` обязан пересобирать расписание.

    Без этого откат правки базы не виден студенту до следующего опроса.
    """
    src = inspect.getsource(editor.cb_undo)
    assert "_rebuild(repo" in src, "откат не пересобирает — план 004"


def test_undo_rebuilds_before_deleting_log_entry():
    """Сначала пересборка, потом удаление записи журнала.

    Иначе при падении отката запись уже стёрта, и повторить нельзя.
    """
    src = inspect.getsource(editor.cb_undo)
    i_rebuild = src.rindex("_rebuild(repo")
    i_delete = src.index("edit_log.delete")
    assert i_rebuild < i_delete, "журнал чистится до пересборки"


def test_undo_rebuilds_base_for_all_days():
    """Правка базы повторяется каждую неделю — пересобираем все дни.

    `_rebuild(repo)` без даты. Для замены — только тот день.
    """
    src = inspect.getsource(editor.cb_undo)
    assert "_rebuild(repo)" in src, "база пересобирается не полностью"
    assert "_rebuild(repo, last.date)" in src, "замена пересобирается не на дату"


def test_rebuild_returns_bool():
    """`_rebuild` сообщает результат, чтобы обработчик не врал."""
    sig = inspect.signature(editor._rebuild)
    assert sig.return_annotation is bool


async def test_rebuild_returns_false_on_failure(monkeypatch):
    """Провал пересборки — False, а не исключение наружу."""
    from tgbot.services import sync_eios

    async def boom(*a, **kw):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(sync_eios, "materialize", boom)
    assert await editor._rebuild(object()) is False


async def test_rebuild_returns_true_on_success(monkeypatch):
    from tgbot.services import sync_eios

    called = []

    async def ok(*a, **kw):
        called.append(1)

    monkeypatch.setattr(sync_eios, "materialize", ok)
    assert await editor._rebuild(object()) is True
    assert called


def test_save_base_reports_failed_rebuild():
    """`_save_base` не должен писать «Сохранено» при провале пересборки."""
    src = inspect.getsource(editor._save_base)
    assert "rebuilt = await _rebuild" in src
    assert "не пересобралось" in src, "нет предупреждения о провале"
    # Успех остаётся успехом.
    assert '"✅ <b>Сохранено</b>" if rebuilt' in src


def test_save_sub_reports_failed_rebuild():
    """То же для замены."""
    src = inspect.getsource(editor._save_sub)
    assert "rebuilt = await _rebuild" in src
    assert "не пересобралось" in src


def test_failed_rebuild_does_not_rollback_edit():
    """Правку не откатываем — она в слоях и корректна.

    Поллер пересоберёт сам через ≤5 минут. Задача — не врать, а не
    отменять работу старосты.
    """
    src = inspect.getsource(editor._save_base)
    # Между `rebuilt = await _rebuild` и текстом не должно быть отката.
    i = src.index("rebuilt = await _rebuild")
    tail = src[i:]
    assert "base_lessons.delete" not in tail
    assert "rollback" not in tail
