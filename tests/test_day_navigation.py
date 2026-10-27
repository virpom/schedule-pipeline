"""С экрана дня и недели есть путь к соседним дням.

План 058, проблема 2. И `_show_day`, и `cb_week` отдавали `BACK_KB` —
одну кнопку «В меню». Чтобы посмотреть завтра, студент выходил в меню
и нажимал другую кнопку: два лишних нажатия на самое частое действие.

Проблема 1 того же плана: «Неделя» показывала скользящие 7 дней
(сегодня..+6), а не пн–вс. Кнопка переименована в «7 дней» — честно и
бесплатно, как и рекомендовал план.
"""
import inspect

from tgbot.handlers import user


def _cbs(kb) -> list[str]:
    return [b.callback_data for row in kb.inline_keyboard for b in row]


def test_nav_kb_exists():
    assert hasattr(user, "NAV_KB")


def test_nav_has_today_and_tomorrow():
    cbs = _cbs(user.NAV_KB)
    assert "day:today" in cbs
    assert "day:tomorrow" in cbs


def test_nav_has_week_and_menu():
    cbs = _cbs(user.NAV_KB)
    assert "week" in cbs
    assert "menu" in cbs, "нет выхода в меню"


def test_day_screen_uses_nav():
    assert "NAV_KB" in inspect.getsource(user._show_day)


def test_week_screen_uses_nav():
    assert "NAV_KB" in inspect.getsource(user.cb_week)


def test_message_buttons_use_nav():
    """Нижняя клавиатура ведёт на те же экраны — навигация и там."""
    for fn in (user.btn_today, user.btn_tomorrow, user.btn_week):
        assert "NAV_KB" in inspect.getsource(fn), f"{fn.__name__} без навигации"


def test_week_button_renamed():
    """«Неделя» — не неделя. Кнопка называет окно честно."""
    assert "🗓 7 дней" in inspect.getsource(user)
    assert 'text="🗓 Неделя"' not in inspect.getsource(user)


def test_old_button_still_works():
    """У пользователей в клавиатуре осталось старое название."""
    src = inspect.getsource(user.btn_week)
    assert "Неделя" in src, "старая кнопка перестанет работать"
