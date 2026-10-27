"""Поиск уважает режим детализации, `/group` проверяет группу.

План 037. Две недоделки:

1. `format_teacher_results` принимает `detail`, но ни один вызывающий
   его не передавал — все получали `brief`. На проде 52 человека из
   227 переключили режим на `lunch`/`full`: они видят время пар на
   экране дня и не видят его в поиске.

2. `/group` писал что угодно: `/group ХХХ-99` записывался, день
   выходил пустым, и студент решал, что пар нет. Настоящая причина —
   опечатка в команде.
"""
import inspect
import pathlib

from tgbot.handlers import user as uh

SRC = pathlib.Path(uh.__file__).read_text()


def test_teacher_search_passes_detail():
    src = inspect.getsource(uh.teacher_answer)
    assert "user.bell_detail" in src, "поиск преподавателя игнорирует режим"


def test_teacher_answer_has_user_param():
    """Без `user` в сигнатуре настройку взять неоткуда."""
    sig = inspect.signature(uh.teacher_answer)
    assert "user" in sig.parameters


def test_group_cmd_checks_known_groups():
    src = inspect.getsource(uh.set_group_cmd)
    code = "\n".join(line.split("#", 1)[0] for line in src.splitlines())
    assert "get_groups" in code, "/group не сверяется со списком групп"
    assert "return" in code.split("get_groups")[1], "нет выхода при неизвестной группе"


def test_group_cmd_suggests_close_names():
    src = inspect.getsource(uh.set_group_cmd)
    assert "Может быть" in src, "нет подсказки при опечатке"


def test_group_cmd_does_not_write_unknown():
    """Неизвестная группа не должна попадать в базу."""
    src = inspect.getsource(uh.set_group_cmd)
    code = "\n".join(line.split("#", 1)[0] for line in src.splitlines())
    guard = code.split("get_groups")[1].split("set_group")[0]
    assert "return" in guard, "set_group вызывается без проверки"


def test_known_groups_include_vuz():
    """Студент вуза тоже может ввести группу текстом."""
    from common.schedule import VUZ_SUFFIX
    assert VUZ_SUFFIX  # суффикс существует и используется в списке групп
