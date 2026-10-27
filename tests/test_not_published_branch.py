"""Ветка «расписание не выложено» была недостижима из-за `deadline_hour`.

План 029. `schedule_file` означает «день материализован», а не «сайт
выложил файл»: `materialize` пишет его на все 14 дней окна, включая
пустые. Все даты в UI лежат внутри окна, значит `published` всегда
True — и до ветки с `deadline_hour` дело не доходило никогда.

Настройка при этом была видна в `/settings` и в меню правки, то есть
создавала иллюзию работающей. Убрал её вместо того, чтобы оставлять
мёртвый код.
"""
import inspect

from tgbot.handlers import admin, user


def test_deadline_hour_removed_from_user_logic():
    """Ветка с дедлайном убрана из выбора сообщения."""
    src = inspect.getsource(user)
    code = "\n".join(line.split("#", 1)[0] for line in src.splitlines())
    assert "deadline_hour" not in code, "ветка с дедлайном вернулась"


def test_deadline_hour_not_in_defaults():
    """И из дефолтов настроек тоже."""
    from infrastructure.database.repo.setting import DEFAULTS

    assert "deadline_hour" not in DEFAULTS


def test_deadline_not_in_settings_screen():
    """Настройка, которая ни на что не влияет, не показывается админу."""
    src = inspect.getsource(admin)
    code = "\n".join(line.split("#", 1)[0] for line in src.splitlines())
    assert "deadline_hour" not in code
    assert "set_deadline" not in code
    assert "adm:set:deadline" not in code


def test_settings_keyboard_has_no_deadline_button():
    kb = admin._settings_kb()
    labels = [b.text for row in kb.inline_keyboard for b in row]
    assert not any("Дедлайн" in t for t in labels), labels


def test_empty_day_still_says_no_lessons():
    """Пустой день внутри окна — «занятий нет», как и было.

    Проверяем, что цепочка условий не потеряла главную ветку.
    """
    src = inspect.getsource(user)
    assert "format_no_lessons(date)" in src
    assert "format_not_published(date)" in src


def test_published_means_materialized():
    """Докстринг объясняет, что `published` — про окно, а не про сайт.

    Без этого следующий читатель снова решит, что признак врёт.
    """
    src = inspect.getsource(user)
    i = src.index("format_not_published(date)")
    context = src[max(0, i - 900):i]
    assert "материализован" in context or "окна" in context, \
        "нет объяснения, что значит published"
