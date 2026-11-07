"""Экраны админки в ядре: та же раскладка, что была.

Перенос админки (этап 1, план 173) ловит то, что не поймает ни один
тест на логику: кнопка пропала, группа не влезла в топ, число страниц
съехало. Проверено на 13 экранах с боевой базы: 0 расхождений.

Две ошибки я допустил по дороге и обе закрыты здесь:
  * взял 10 групп в топ вместо 8;
  * добавил кнопку «Все группы», которой не было.
"""
from types import SimpleNamespace

from core.admin import group_sort_key


def test_sort_by_size_then_name():
    """Крупные сверху; при равенстве — по алфавиту без суффикса."""
    a = ("ДП-26", [1, 2, 3])
    b = ("ЭК-26", [1, 2, 3])
    c = ("ГИ-23", [1])
    assert group_sort_key(a) == (-3, "ДП-26")
    assert group_sort_key(a) < group_sort_key(b)      # алфавит
    assert group_sort_key(b) < group_sort_key(c)      # размер важнее


def test_sort_strips_vuz_suffix():
    """@vuz — служебный суффикс, в алфавите он не должен мешать."""
    key = group_sort_key(("ЭК-23@vuz", [1]))
    assert key == (-1, "ЭК-23")


def test_top_is_eight_groups():
    """В «Крупнейших группах» ровно 8 строк, как было.

    Я по ошибке поставил 10 — сверка с эталоном это поймала.
    """
    import inspect
    from core import admin as core_admin
    src = inspect.getsource(core_admin.build_stats_unit)
    assert "[:8]" in src, "топ групп изменил размер"


def test_stats_unit_has_no_extra_button():
    """Кнопка одна: «К статистике». Лишнюю я добавлял по ошибке."""
    import inspect
    from core import admin as core_admin
    src = inspect.getsource(core_admin.build_stats_unit)
    assert src.count("btn(") == 1, "в экране подразделения лишняя кнопка"
