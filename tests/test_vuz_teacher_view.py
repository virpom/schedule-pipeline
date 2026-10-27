"""Преподаватель вуза: замены видны, пары не дублируются, неделя не пуста.

План 006. `_vuz_teacher_day` читал `base_lesson` напрямую, минуя
`get_day_slots`. Три следствия:

1. Замены вуза не применялись — их 160, а в base_lesson их нет.
2. `_user_lessons_range` вуз не включал вовсе: у преподавателя только
   с вузовскими парами экран «Неделя» был пустым, хотя «Сегодня»
   показывал шесть дней с парами.
3. Одна пара дублировалась по числу групп, где преподаватель ведёт:
   format_day склеивает по точному совпадению предмета, а «(лек.)» и
   «(лек)» — разные ключи.

На проде 27.10 вузовских преподавателей в боте нет (3 зарегистрированы,
все колледжные), дефект латентный. Но задевает сразу, как
зарегистрируется первый.
"""
import datetime
import inspect

from tgbot.handlers import user as uh
from tgbot.services.schedule_layer import Slot


def test_day_goes_through_final_layer():
    """Итоговый слой, а не чтение base_lesson напрямую."""
    src = inspect.getsource(uh._vuz_teacher_day)
    assert "get_day_slots" in src, "замены не применяются"
    assert "get_for_teacher(" not in src, "осталось прямое чтение base_lesson"


def test_day_filters_to_his_lessons():
    """Из get_day_slots группы берутся только свои пары."""
    src = inspect.getsource(uh._vuz_teacher_day)
    assert "_slot_is_his" in src


def test_range_includes_vuz():
    """Неделя не может быть пустой, когда день полон."""
    src = inspect.getsource(uh._user_lessons_range)
    assert "_vuz_teacher_day" in src, "вуз не попал в недельный экран"


def test_slot_has_date():
    """format_week группирует по дате — без поля экран падал бы."""
    assert "date" in Slot.__slots__


def test_date_set_for_vuz_slots():
    src = inspect.getsource(uh._vuz_teacher_day)
    assert "slot.date = date" in src


def _s(para, subject, teacher="Иванова З.Н.", group="Г-1"):
    return Slot(para, subject, teacher, group=group)


def test_dedupe_merges_same_lesson():
    slots = [_s(4, "Теория вероятностей (лек.)", group=f"Г-{i}") for i in range(3)]
    assert len(uh._dedupe_slots(slots)) == 1


def test_dedupe_merges_dot_variants():
    """«(лек.)» и «(лек)» — один предмет."""
    slots = [_s(4, "Теория вероятностей (лек.)", group="А"),
             _s(4, "Теория вероятностей (лек)", group="Б")]
    assert len(uh._dedupe_slots(slots)) == 1


def test_dedupe_collects_groups():
    slots = [_s(4, "Математика", group="А"), _s(4, "Математика", group="Б")]
    out = uh._dedupe_slots(slots)
    assert len(out) == 1
    assert "А" in out[0].group and "Б" in out[0].group


def test_dedupe_keeps_different_paras():
    assert len(uh._dedupe_slots([_s(1, "Математика"), _s(2, "Математика")])) == 2


def test_dedupe_keeps_different_teachers():
    assert len(uh._dedupe_slots(
        [_s(1, "Математика"), _s(1, "Математика", teacher="Петров А.А.")])) == 2


def test_dedupe_keeps_paired_and_single():
    """Пара 1–2 и пара 2 — разные занятия, не схлопывать."""
    a = Slot(1, "Математика", para_end=2)
    b = Slot(2, "Математика")
    assert len(uh._dedupe_slots([a, b])) == 2


def test_teacher_groups_exists():
    from infrastructure.database.repo.base_lesson import BaseLessonRepo

    assert hasattr(BaseLessonRepo, "get_teacher_groups")
    sig = inspect.signature(BaseLessonRepo.get_teacher_groups)
    assert "weekday" in sig.parameters


def test_vuz_slots_carry_date():
    """Дата проставляется, иначе сортировка недели упадёт."""
    slot = _s(1, "Математика")
    assert slot.date is None
    slot.date = datetime.date(2026, 10, 27)
    assert slot.date == datetime.date(2026, 10, 27)
