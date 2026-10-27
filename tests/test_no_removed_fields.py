"""Никто не вызывает методы удалённых полей.

Дважды подряд удаление поля из модели оставляло живой вызов:

* план 038 убрал `users.unit` и `set_unit`, но в `cb_group` остался
  `await repo.users.set_unit(...)` — любой, кто выбирал группу, получал
  `AttributeError` (на проде 5 раз за час, 27.10);
* план 030 убрал `repo.no_lessons`, и такие же висячие вызовы пришлось
  искать вручную.

Тест статический: он не требует БД и ловит вызов до деплоя.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Удалённые методы репозитория -> когда удалены.
REMOVED = {
    "set_unit": "план 038 (миграция 0010)",
    "set_deadline": "план 029",
    "no_lessons": "план 030",
}


def _sources():
    for path in ROOT.rglob("*.py"):
        if ".venv" in path.parts or "tests" in path.parts:
            continue
        if "migrations" in path.parts:
            continue          # там исторические упоминания в докстрингах
        yield path


def test_no_calls_to_removed_repo_methods():
    bad = []
    for path in _sources():
        text = path.read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), 1):
            code = line.split("#", 1)[0]
            for name, when in REMOVED.items():
                # Ищем именно вызов: `.name(` — а не упоминание в тексте.
                if re.search(rf"\.{name}\s*\(", code):
                    bad.append(f"{path.relative_to(ROOT)}:{line_no} "
                               f"-> .{name}() удалён ({when})")
    assert not bad, "висячие вызовы удалённых методов:\n" + "\n".join(bad)


def test_no_unit_attribute_access():
    """`user.unit` / `.unit =` больше не читается и не пишется.

    Докстринги не считаем: в них осталось объяснение, почему поле
    убрали, и это полезно.
    """
    import ast

    bad = []
    for path in _sources():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "unit":
                bad.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert not bad, "обращение к удалённому users.unit:\n" + "\n".join(bad)


def test_group_selection_does_not_touch_unit():
    """`cb_group` — тот самый путь, что падал на проде."""
    import inspect

    from tgbot.handlers import user as user_handler

    src = inspect.getsource(user_handler.cb_group)
    code = "\n".join(line.split("#", 1)[0] for line in src.splitlines())
    assert "set_unit" not in code
    assert "unit" not in code
