"""Фильтр ручных замен вуза ограничен вузом (план 118).

replace_vuz_changes собирал manual_keys по ВСЕМ строкам substitution с
source != 'vuz', включая колледжные. Замена вуза на совпавший ключ
(дата, группа, пара) молча не записывалась, а return added + len(manual)
сообщал число, в котором ручные замены считались «обновлёнными вузом».

Сейчас группы колледжа и вуза не пересекаются (@vuz), поэтому вреда не
было — но условие держалось на совпадении имён, а не на коде. У соседнего
replace_vuz_lessons ограничение стояло с самого начала.
"""
import inspect

from tgbot.services import sync_vuz


def _src(fn) -> str:
    return inspect.getsource(fn)


def test_changes_filter_limited_to_vuz():
    src = _src(sync_vuz.replace_vuz_changes)
    assert "Substitution.group.like" in src, \
        "фильтр ручных замен снова без ограничения по вузу"


def test_lessons_filter_still_limited():
    src = _src(sync_vuz.replace_vuz_lessons)
    assert "BaseLesson.group.like" in src


def test_changes_returns_only_own():
    """Ответ — сколько записал этот вызов, без чужих ручных замен."""
    src = _src(sync_vuz.replace_vuz_changes)
    assert "return added" in src
    assert "return added + len(manual)" not in src


def test_lessons_counter_not_touched():
    """В replace_vuz_lessons manual уже ограничен вузом — там можно."""
    src = _src(sync_vuz.replace_vuz_lessons)
    assert "return added + len(manual)" in src
