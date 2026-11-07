"""Ядро не знает про Telegram.

Главная причина, по которой этап 1 вообще делается: если `core/`
потянет aiogram, то второй бот (MAX) не сможет его переиспользовать, и
вся работа окажется напрасной. Поэтому правило проверяется тестом, а не
памятью.

Правило: в `core/` нет импортов `aiogram` и нет импортов `tgbot`.
"""
import ast
from pathlib import Path

CORE = Path(__file__).resolve().parents[1] / "core"

FORBIDDEN = ("aiogram", "tgbot", "telebot", "maxapi")


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                out.add(a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                out.add(node.module.split(".")[0])
            elif node.level:
                # Относительный импорт внутри core — это core.
                out.add("core")
    return out


def test_core_files_exist():
    files = list(CORE.glob("*.py"))
    assert files, "пакет core пуст"


def test_core_does_not_import_platforms():
    bad = []
    for path in CORE.glob("*.py"):
        hit = _imports(path) & set(FORBIDDEN)
        if hit:
            bad.append(f"{path.name}: {sorted(hit)}")
    assert not bad, "ядро тянет платформу: " + "; ".join(bad)


def test_core_does_not_import_tgbot():
    """Отдельно и явно: tgbot — это адаптер, зависимость только в одну сторону."""
    for path in CORE.glob("*.py"):
        assert "tgbot" not in _imports(path), f"{path.name} импортирует tgbot"
