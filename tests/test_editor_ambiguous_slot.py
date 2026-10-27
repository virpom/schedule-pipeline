"""Редактор не путает строки одного слота у вуза.

План по рангу 14. `get_day` без `week` возвращает для вуза все строки
слота, но редактор строил `Slot(...)` без `weeks` и брал первую через
`next()`. На проде **425 вузовских слотов** имеют по несколько строк.

Живой пример (АП-25оз@vuz, вторник, пара 7):

    weeks='13'            Компьютерное моделирование, ч.1
    weeks='5,6'           Основы военной подготовки (лек.)
    weeks='7,8'           Основы военной подготовки
    weeks='9,10,11,12'    Компьютерное моделирование, ч.1 (лек.)

Староста видел одну дисциплину и правил не ту, а upsert с пустым
weeks создавал новую строку, видимую на всех неделях сразу.
"""
import inspect

from tgbot.handlers import editor
from tgbot.services.schedule_layer import Slot


def test_slot_has_weeks():
    assert "weeks" in Slot.__slots__


def test_slot_weeks_default_empty():
    assert Slot(1, "Математика").weeks == ""


def test_slot_weeks_kept():
    s = Slot(7, "ОП", weeks="5,6")
    assert s.weeks == "5,6"


def test_day_render_keeps_weeks():
    """Слоты дня собираются с weeks, иначе варианты схлопнутся."""
    src = inspect.getsource(editor._render_base_slots)
    assert "weeks=l.weeks" in src, "weeks теряется при сборке Slot"


def test_slot_screen_shows_variants():
    """Экран пары перечисляет все строки слота, а не одну."""
    src = inspect.getsource(editor.cb_base_slot)
    assert "len(here)" in src, "нет разбора нескольких вариантов"
    assert "недели:" in src, "недели не показаны"


def test_picker_registered():
    assert hasattr(editor, "cb_pick_variant"), "нет выбора варианта"


def test_picker_action_buttons_carry_weeks():
    """Кнопка действия несёт weeks — без него правится не та строка."""
    src = inspect.getsource(editor.slot_actions_kb)
    assert "weeks: str" in src
    assert "ed:edit:{weekday}:{parity}:{para}:{wk}" in src


def test_save_uses_chosen_weeks():
    src = inspect.getsource(editor._save_base)
    assert 'data.get("weeks")' in src, "недели не берутся из выбора"
    assert '(l.weeks or "") == weeks' in src, "строка не сопоставлена по weeks"


def test_delete_uses_button_weeks():
    src = inspect.getsource(editor.cb_del_base)
    assert "weeks_in" in src
    assert 'parts[5] == "_"' in src


def test_edit_callback_parses_weeks():
    # переносы строк в исходнике склеиваем: update_data стоит на двух строках
    src = " ".join(inspect.getsource(editor.cb_edit_base).split())
    assert "parts = cb.data.split" in src
    assert 'parts[5] == "_"' in src
    assert "para=para, weeks=weeks" in src, "выбранные недели не попали в state"
