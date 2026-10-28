"""Рассылка склеивает поток и не теряет кабинет (083 и 164).

План 083: format_day в рассылке звался без merge_groups, поэтому
преподаватель на потоке получал шесть одинаковых строк в рассылке и
одну на экране дня. Задевало 2 человека каждый день.

План 164 всплыл по дороге: _merge_groups склеивала пары потока и
оставляла кабинет первой группы. Комментарий обещал обратное («терять
её всё равно нельзя — она останется от первой группы»). На проде 3
таких слота: «Начертательная геометрия», Лаговская Е.В., М-310 и М-103.
"""
import datetime
import inspect

from common.schedule import _merge_groups, format_day
from tgbot.services import poller
from tgbot.services.schedule_layer import Slot


def _stream(rooms):
    return [Slot(1, "Физическая культура", "Сидоров С.С.", room, group=f"Г-{i+1}")
            for i, room in enumerate(rooms)]


def test_broadcast_passes_merge_flag():
    assert "merge_groups=is_teacher" in inspect.getsource(poller.notify_new_schedule)


def test_stream_collapses_in_broadcast_format():
    got = _merge_groups(_stream(["зал"] * 6))
    assert len(got) == 1
    assert got[0].group.count(",") == 5


def test_different_rooms_kept():
    got = _merge_groups(_stream(["М-310", "М-103"]))
    assert len(got) == 1, "должны склеиться: предмет/препод/слот совпадают"
    assert "М-310" in got[0].room and "М-103" in got[0].room, got[0].room


def test_same_room_not_doubled():
    got = _merge_groups(_stream(["зал", "зал", "зал"]))
    assert got[0].room == "зал", got[0].room


def test_room_rendered_in_day():
    d = datetime.date(2026, 11, 9)
    lessons = _merge_groups(_stream(["М-310", "М-103"]))
    text = format_day(d, lessons, {}, {}, meta="group", merge_groups=True)
    assert "М-310" in text and "М-103" in text, text


def test_student_screen_unaffected():
    """Для студента склейки нет — флаг по умолчанию False."""
    got = _merge_groups(_stream(["зал"])) * 3
    text = format_day(datetime.date(2026, 11, 9), got, {}, {}, meta="teacher")
    assert text.count("Физическая культура") == 3
