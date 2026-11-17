"""«Конец пары» рассказывает, что дальше.

Просьба из чата: после звонка об окончании непонятно, какая пара
следующая, во сколько и сколько ждать. Данные для этого уже есть —
`_tick` держит в руках все пары дня, когда собирает звонки, поэтому
фича не добавляет ни одного запроса в базу.

Правила, которые здесь закреплены:
  * дописывается только к «Конец пары», не к началу, перемене и обеду;
  * отменённые пары пропускаются — иначе студент шёл бы на отменённую;
  * время берётся из time_note, если оно есть, иначе из сетки звонков;
  * «через N мин» только на понятном горизонте (до 3 часов) — иначе
    в звонке о паре в 09:00 висело бы «через 480 мин»;
  * после последней пары строки нет вовсе.
"""
import datetime
from types import SimpleNamespace


from tgbot.services import bell as bell_mod

DT = "OTHER"


def _lesson(para, subject, *, para_end=None, action="", changed=False,
            teacher="", room="", time_note="", group="ДП-26"):
    return SimpleNamespace(
        para=para, para_end=para_end or para, subject=subject,
        action=action, changed=changed, teacher=teacher, room=room,
        time_note=time_note, group=group,
    )


def _grid(*pairs):
    """Сетка звонков: (пара, начало, конец) → как её отдаёт get_context."""
    out = {}
    for para, start, end in pairs:
        out[(DT, "I_IV", para)] = SimpleNamespace(
            start=datetime.time(*start), end=datetime.time(*end),
            h1_end=datetime.time(*end), h2_start=datetime.time(*end),
        )
    return out


def _cg(group):
    return "I_IV"


def _user():
    return SimpleNamespace(id=1, role="student", group="ДП-26", course=1)


def _call(text, key, lessons, grid):
    return bell_mod._with_next(text, key, lessons, grid, DT, _cg, _user())


def test_appends_next_lesson_to_end_of_pair():
    """К «Конец пары» дописана следующая пара с преподавателем и кабинетом."""
    lessons = [
        _lesson(1, "Правоведение"),
        _lesson(2, "Организация документооборота", teacher="Харькова Д.А.",
                room="ауд. 406", changed=True),
    ]
    grid = _grid((1, (9, 0), (10, 35)), (2, (10, 45), (12, 40)))

    out = _call("🔔 Конец пары", "e:1", lessons, grid)

    assert out.startswith("🔔 Конец пары\n")
    assert "следующая пара" in out
    assert "Организация документооборота 🔄" in out
    assert "Харькова Д.А. · ауд. 406" in out


def test_no_next_after_last_lesson():
    """После последней пары строки нет — иначе шум в каждом звонке."""
    lessons = [_lesson(1, "Правоведение")]
    grid = _grid((1, (9, 0), (10, 35)))

    assert _call("🔔 Конец пары", "e:1", lessons, grid) == "🔔 Конец пары"


def test_cancelled_next_is_skipped():
    """Отменённая пара не может быть «следующей»."""
    lessons = [
        _lesson(1, "Правоведение"),
        _lesson(2, "Отменённое", action="cancel"),
        _lesson(3, "Физика"),
    ]
    grid = _grid((1, (9, 0), (10, 35)), (2, (10, 45), (12, 40)),
                 (3, (12, 50), (14, 25)))

    out = _call("🔔 Конец пары", "e:1", lessons, grid)

    assert "Отменённое" not in out
    assert "Физика" in out


def test_only_end_of_pair_is_extended():
    """Начало пары, перемена и обед остаются как были."""
    lessons = [_lesson(1, "Правоведение"), _lesson(2, "Физика")]
    grid = _grid((1, (9, 0), (10, 35)), (2, (10, 45), (12, 40)))

    for key in ("s:1", "h1:1", "h2:1", "lunch", "lunch_end"):
        assert _call("🔔 текст", key, lessons, grid) == "🔔 текст"


def test_time_note_wins_over_grid():
    """Своё время из ячейки сильнее сетки звонков."""
    lessons = [
        _lesson(1, "Правоведение"),
        _lesson(7, "Вечерняя", time_note="с 18.00 до 21.00"),
    ]
    grid = _grid((1, (9, 0), (10, 35)), (7, (18, 50), (20, 20)))

    out = _call("🔔 Конец пары", "e:1", lessons, grid)

    assert "с 18.00 до 21.00" in out
    assert "23:50" not in out


def test_no_countdown_for_far_lesson():
    """«через N мин» только на близком горизонте.

    Иначе звонок о паре в 09:00 показывал бы «через 480 мин».
    """
    lessons = [_lesson(1, "Утро"), _lesson(6, "Вечер")]
    grid = _grid((1, (9, 0), (10, 35)), (6, (18, 5), (19, 40)))

    # Время в тесте — «сейчас», поэтому горизонт проверяем отдельно:
    # подсовываем звонок на завтра, до него точно больше трёх часов.
    far = datetime.datetime.now() + datetime.timedelta(hours=8)
    grid[(DT, "I_IV", 6)].start = far.time()

    out = _call("🔔 Конец пары", "e:1", lessons, grid)

    assert "через" not in out


def test_teacher_gets_line_too():
    """У преподавателя та же строка — он ведёт другой группе."""
    lessons = [
        _lesson(1, "Правоведение", group="ЮР-25А"),
        _lesson(2, "Право", group="ЮР-24Б", teacher="Иванов И.И."),
    ]
    grid = _grid((1, (9, 0), (10, 35)), (2, (10, 45), (12, 40)))

    out = _call("🔔 Конец пары", "e:1", lessons, grid)

    assert "Право" in out


def test_empty_day_does_not_break():
    """Пустой день не роняет звонок."""
    assert _call("🔔 Конец пары", "e:1", [], {}) == "🔔 Конец пары"
