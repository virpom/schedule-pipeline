"""Курс колледжа выводится из группы, а не спрашивается у человека.

Бот показывал экран «на каком ты курсе?» с кнопками 1–4 и хранил ответ
в users.course. Курс и так зашит в номер набора — ДП-26 это 1 курс, —
поэтому вопрос был лишним шагом, на котором ошибались.

На проде разошлось 9 записей из 297:
  ДП-26  → 3 (верно 1)
  СМф-24 → 1 (верно 3)
  ЭК-25  → 1 (верно 2)
  СМк-25 → 1 (верно 2), дважды
  ПР-26КП → 2 (верно 1)
  ЮР-24Б → 2 (верно 3)
  ПРф-25 → 3 (верно 2)
  ЮР-25Б → 3 (верно 2)

Это не косметика: курс выбирает поток звонков. У колледжа 1 и 4 курс —
поток I_IV, 2 и 3 — II_III. Студент с чужим курсом видел чужое время.
"""
from pathlib import Path

from common.schedule import course_from_group, course_group_from_group

ROOT = Path(__file__).resolve().parents[1]


def test_course_from_real_groups():
    """Реальные имена групп с прода дают верный курс."""
    expected = {
        "ДП-26": 1, "ПР-26КП": 1, "ТЭк-26": 1, "ЮР-26Б": 1, "СМ-26КП": 1,
        "СМк-25": 2, "ЭК-25": 2, "ЮР-25Б": 2, "ПРф-25": 2, "ДОУ-25": 2,
        "СМф-24": 3, "ЮР-24Б": 3, "ЭОф-24": 3, "ТЭф-24": 3, "ДОУ-24": 3,
        "ЭК-23": 4, "ПСО-23": 4,
    }
    for group, want in expected.items():
        assert course_from_group(group) == want, f"{group}: {course_from_group(group)} != {want}"


def test_vuz_sixth_year_not_capped():
    """Вуз доходит до 6 курса — обрезать нельзя."""
    assert course_from_group("ГИ-21") >= 5


def test_bells_stream_matches_course():
    """Поток звонков следует из группы, а не из поля course."""
    assert course_group_from_group("ЭК-23") == "I_IV"
    assert course_group_from_group("ДП-26") == "I_IV"
    assert course_group_from_group("СМк-25") == "II_III"
    assert course_group_from_group("ЭОф-24") == "II_III"


def test_no_manual_course_keyboard_left():
    """Экрана «на каком ты курсе?» больше нет."""
    src = (ROOT / "tgbot/handlers/user.py").read_text()
    assert "COURSE_KB" not in src, "кнопки выбора курса остались"
    assert "На каком ты курсе" not in src, "вопрос о курсе остался"


def test_menu_shows_course_from_group():
    """Подпись в меню считается из группы и для колледжа."""
    src = (ROOT / "tgbot/handlers/user.py").read_text()
    block = src[src.index("def menu_text"):src.index("def _render_menu")]
    assert "course_from_group(user.group)" in block, block


def test_group_pick_sets_course():
    """При выборе группы курс записывается сразу."""
    src = (ROOT / "tgbot/handlers/user.py").read_text()
    assert src.count("set_course(user.id, course_from_group(group))") >= 2


def test_migration_recomputes_course(tmp_path):
    """Миграция чинит уже записанные строки."""
    import importlib.util

    path = ROOT / "migrations/versions/0014_user_course_from_group.py"
    spec = importlib.util.spec_from_file_location("mig0014", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    assert mod._course("ДП-26") == 1
    assert mod._course("СМф-24") == 3
    assert mod._course("ЭК-23") == 4
    # Совпадает с боевой функцией на всех группах с прода.
    for g in ["ДП-26", "СМк-25", "ЭОф-24", "ЭК-23", "ПСО-23", "ГИ-21"]:
        assert mod._course(g) == course_from_group(g), g


def test_migration_upgrades_rows(tmp_path):
    """На живой таблице: ошибочный курс приводится к верному."""
    import importlib.util

    from sqlalchemy import create_engine, text

    engine = create_engine(f"sqlite:///{tmp_path}/db.sqlite")
    with engine.begin() as c:
        c.execute(text('create table users (id integer primary key, '
                       '"group" varchar, course integer, role varchar)'))
        c.execute(text("insert into users values (1,'ДП-26',3,'student')"))
        c.execute(text("insert into users values (2,'СМф-24',1,'student')"))
        c.execute(text("insert into users values (3,'ЭК-23',4,'student')"))
        c.execute(text("insert into users values (4,null,2,'student')"))
        c.execute(text("insert into users values (5,'ДП-26',3,'teacher')"))

    path = ROOT / "migrations/versions/0014_user_course_from_group.py"
    spec = importlib.util.spec_from_file_location("mig0014b", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    class _Ops:
        def get_bind(self):
            return conn_holder[0]

    conn_holder = [engine.connect()]
    mod.op = _Ops()
    try:
        mod.upgrade()
    finally:
        conn_holder[0].commit()

    with engine.begin() as c:
        rows = dict(c.execute(text("select id, course from users")).fetchall())
    assert rows[1] == 1, "ДП-26 не исправлен"
    assert rows[2] == 3, "СМф-24 не исправлен"
    assert rows[3] == 4, "ЭК-23 не тронут (был верный)"
    assert rows[4] == 2, "без группы не трогаем"
    assert rows[5] == 3, "преподавателя не трогаем"
    engine.dispose()
