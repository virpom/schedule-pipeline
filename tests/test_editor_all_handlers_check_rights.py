"""Каждый обработчик редактора проверяет права сам.

Пять обработчиков (cb_skip_teacher, cb_sub_skip_teacher,
cb_teacher_suggestion, on_teacher, on_room) прав не проверяли. Сами по
себе они безобидны — запись в базу идёт через _save_base/_save_sub, а
те права проверяют. Но они пишут в состояние FSM, и защита держалась на
одном рубеже вместо двух.

Теперь проверка есть в каждом. Тест стережёт, чтобы новый обработчик
не появился без неё: это дешевле, чем помнить правило.
"""
import re
from pathlib import Path

SRC = (Path(__file__).resolve().parents[1]
       / "tgbot/handlers/editor.py").read_text()


def _handlers() -> list[tuple[str, str]]:
    """(имя, тело) для каждого @editor_router."""
    parts = re.split(r"\n(?=@editor_router)", SRC)
    out = []
    for p in parts:
        if not p.startswith("@editor_router"):
            continue
        m = re.search(r"async def (\w+)", p)
        if m:
            out.append((m.group(1), p))
    return out


def test_every_handler_checks_rights():
    missing = [name for name, body in _handlers() if "editor_group(" not in body]
    assert not missing, f"без проверки прав: {missing}"


def test_handler_count_sane():
    """Сторож на случай, если разбор сломается и «проверка» станет пустой."""
    assert len(_handlers()) >= 30, f"нашлось только {len(_handlers())} обработчиков"


def test_previously_unprotected_now_protected():
    """Именно те пять, что были без проверки."""
    by_name = dict(_handlers())
    for name in ("cb_skip_teacher", "cb_sub_skip_teacher",
                 "cb_teacher_suggestion", "on_teacher", "on_room"):
        assert name in by_name, f"обработчик {name} пропал"
        assert "editor_group(" in by_name[name], f"{name} снова без проверки"


def test_rights_denied_is_answered():
    """Отказ виден человеку, а не молчит."""
    by_name = dict(_handlers())
    for name in ("cb_skip_teacher", "cb_sub_skip_teacher", "cb_teacher_suggestion"):
        body = by_name[name]
        assert "show_alert=True" in body or "Нет прав" in body, name
