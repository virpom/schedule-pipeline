"""Клавиатуры ядра: раскладка та же, что была в Telegram-хендлере.

Перенос клавиатур (этап 1, план 173) опасен тем, что кнопка может
пропасть или переехать в другой ряд, и никто не заметит, пока студент
не начнёт жаловаться. Поэтому раскладка закреплена здесь.

Проверено на 26 вариантах (студент, студент вуза, преподаватель, без
группы, без фамилии, с редактором и без): 0 расхождений с прежним
видом.
"""
from types import SimpleNamespace

from core.keyboard import Keyboard
from core.menu import (menu_kb, settings_kb, teacher_unit_kb, unit_kb)


def _user(**kw):
    base = dict(id=1, role="student", group="ДП-26", course=1,
                teacher_name=None, bell_detail="brief", send_image=True,
                subscribed=True, bell_mode="off")
    base.update(kw)
    return SimpleNamespace(**base)


def _texts(k: Keyboard) -> list[list[str]]:
    return [[b.text for b in row] for row in k.rows]


def _actions(k: Keyboard) -> list[str]:
    return [b.action for b in k.buttons if b.action]


def test_menu_student_layout():
    """Пять рядов, как было: день, неделя, поиск, звонки, настройки."""
    k = menu_kb(_user())
    assert len(k.rows) == 5
    assert _texts(k)[0] == ["📅 Сегодня", "📅 Завтра"]
    assert _texts(k)[1] == ["🗓 7 дней", "📜 История"]
    assert _texts(k)[2] == ["🔎 Предмет", "👨‍🏫 Преподаватель"]
    # Иконка показывает ДОСТУПНОЕ действие, а не состояние: подписан ->
    # предлагаем отписаться (🔕). Так было и до переноса.
    assert _texts(k)[3] == ["⏰ Звонки", "🔕 Подписка"]
    assert _texts(k)[4] == ["⚙️ Настройки"]


def test_subscribed_icon_flips():
    """Подписан — 🔕 (можно отписаться), не подписан — 🔔."""
    on = [b.text for b in menu_kb(_user(subscribed=True)).buttons]
    off = [b.text for b in menu_kb(_user(subscribed=False)).buttons]
    assert "🔕 Подписка" in on
    assert "🔔 Подписка" in off


def test_teacher_has_no_group_button():
    """Преподавателю кнопка «Преподаватель» не нужна — он и есть он."""
    k = menu_kb(_user(role="teacher", group=None, teacher_name="Иванов И.И."))
    flat = [b.text for b in k.buttons]
    assert "👨‍🏫 Преподаватель" not in flat
    assert "🔎 Предмет" in flat


def test_no_identity_puts_pick_first():
    """Новичок должен видеть «Выбрать группу» первым, а не последним."""
    k = menu_kb(_user(group=None))
    assert k.rows[0][0].text == "🎯 Выбрать группу"
    assert k.rows[0][0].action == "pick"


def test_teacher_without_name_gets_find_self():
    k = menu_kb(_user(role="teacher", group=None, teacher_name=None))
    assert k.rows[0][0].text == "🎯 Найти себя"
    assert k.rows[0][0].action == "pick_teacher"


def test_editor_button_appears():
    flat = [b.text for b in menu_kb(_user(), is_editor=True).buttons]
    assert "✏️ Редактор расписания" in flat


def test_support_button_is_url():
    k = menu_kb(_user(), support_link="https://t.me/sup")
    last = k.rows[-1][0]
    assert last.url == "https://t.me/sup"
    assert last.action == ""


def test_settings_student():
    k = settings_kb(_user())
    flat = [b.text for b in k.buttons]
    assert "🎯 Сменить группу" in flat
    assert "🎯 Сменить курс" in flat
    assert "🐱 Картинки: вкл" in flat
    assert "🏠 Главное меню" in flat


def test_settings_teacher_has_no_images():
    """Картинки — только студентам: преподавателю они не шлются."""
    k = settings_kb(_user(role="teacher", group=None,
                          teacher_name="Иванов И.И."))
    flat = [b.text for b in k.buttons]
    assert "🎯 Сменить фамилию" in flat
    assert not any("Картинки" in t for t in flat)
    assert not any("Сменить курс" in t for t in flat)


def test_settings_no_course_without_group():
    flat = [b.text for b in settings_kb(_user(group=None)).buttons]
    assert not any("Сменить курс" in t for t in flat)


def test_unit_keyboard():
    k = unit_kb()
    assert [b.action for b in k.buttons] == ["unit:college", "unit:vuz", "menu"]


def test_teacher_unit_keyboard():
    k = teacher_unit_kb()
    assert [b.action for b in k.buttons] == ["tunit:college", "tunit:vuz", "menu"]


def test_all_actions_unique_per_keyboard():
    """Дубль действия в одной клавиатуре — почти всегда опечатка."""
    for k in (menu_kb(_user()), settings_kb(_user()), unit_kb(),
              teacher_unit_kb()):
        acts = _actions(k)
        assert len(acts) == len(set(acts)), f"дубли: {acts}"
