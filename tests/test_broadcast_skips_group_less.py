"""Подписчик без группы не получает «Занятий нет» (план 098).

notify_new_schedule рассылал по всем get_subscribed() без проверки, есть
ли у человека группа или фамилия. Ветка else — запасная, в неё попадали
все, кто не «преподаватель с фамилией», и get_for_group_date(None, date)
выполнял WHERE "group" IS NULL — пусто.

Дальше format_no_lessons, и человек получал «Занятий нет 🙌» на каждую
дату окна: 15 ложных уведомлений, и ни одного настоящего.

На проде таких трое (не пять, как в плане — цифра была снята раньше).
Плюс преподаватель с ролью teacher, но без фамилии.
"""
import asyncio
import datetime
from types import SimpleNamespace


D = datetime.date(2026, 11, 9)


def _user(uid, role, group=None, teacher=None, send_image=False):
    return SimpleNamespace(id=uid, role=role, group=group, teacher_name=teacher,
                           bell_detail="brief", send_image=send_image, course=1)


def _run(subscribers, changes, monkeypatch):
    sent = []

    async def fake_broadcast(bot, items, rate, blocked=None):
        sent.extend(items)

    async def get_subscribed():
        return subscribers

    async def get_all():
        return []

    async def get_context():
        return {}, {}

    async def get_group_course_map():
        return {}

    async def for_group_date(group, date):
        return [SimpleNamespace(para=1, subject="Математика", teacher="И",
                                room="1", changed=False, action="", comment="",
                                group=group, time_note="", para_end=None)] if group else []

    async def for_teacher_date(name, date):
        return []

    repo = SimpleNamespace(
        bell_schedule=SimpleNamespace(get_context=get_context),
        users=SimpleNamespace(get_subscribed=get_subscribed,
                              get_group_course_map=get_group_course_map),
        chats=SimpleNamespace(get_all=get_all),
        no_lessons=SimpleNamespace(get_note=_none),
        college_lessons=SimpleNamespace(get_for_group_date=for_group_date,
                                        get_for_teacher_date=for_teacher_date),
    )

    class Pool:
        def __call__(self):
            class Ctx:
                async def __aenter__(self):
                    return None

                async def __aexit__(self, *a):
                    return False
            return Ctx()

    import tgbot.services.poller as pm
    monkeypatch.setattr(pm, "RequestsRepo", lambda db: repo)
    monkeypatch.setattr(pm, "broadcast_schedule", fake_broadcast)
    monkeypatch.setattr(pm.photos, "random_photo", lambda *a, **k: None)
    monkeypatch.setattr(pm.photos, "weekday_folder", lambda d: "monday")
    monkeypatch.setattr(pm, "format_day", lambda *a, **k: "ПАРЫ")
    monkeypatch.setattr(pm, "format_no_lessons", lambda *a, **k: "ЗАНЯТИЙ НЕТ")
    monkeypatch.setattr(pm, "bells_group", lambda g, c: None)

    asyncio.run(pm.notify_new_schedule(None, Pool(), changes, 0.0, "/tmp"))
    return sent


async def _none(*a, **k):
    return None


def test_user_without_group_skipped(monkeypatch):
    sent = _run([_user(1, "student", group=None)], [(D, False, set())], monkeypatch)
    assert sent == [], f"без группы получил сообщение: {sent}"


def test_teacher_without_name_skipped(monkeypatch):
    sent = _run([_user(2, "teacher", teacher=None)], [(D, False, set())], monkeypatch)
    assert sent == [], f"teacher без фамилии получил: {sent}"


def test_normal_student_still_gets(monkeypatch):
    sent = _run([_user(3, "student", group="ДП-26")], [(D, False, set())], monkeypatch)
    assert len(sent) == 1, sent
    assert sent[0][0] == 3


def test_teacher_with_name_still_gets(monkeypatch):
    sent = _run([_user(4, "teacher", teacher="Данилова А.Н.")],
                [(D, False, set())], monkeypatch)
    assert len(sent) == 1, sent


def test_mixed_only_valid(monkeypatch):
    sent = _run([_user(1, "student", group=None),
                 _user(3, "student", group="ДП-26"),
                 _user(2, "teacher", teacher=None),
                 _user(4, "teacher", teacher="Данилова А.Н.")],
                [(D, False, set())], monkeypatch)
    ids = [s[0] for s in sent]
    assert ids == [3, 4], ids


def test_no_false_no_lessons_text(monkeypatch):
    sent = _run([_user(1, "student", group=None)], [(D, False, set())], monkeypatch)
    assert all("ЗАНЯТИЙ НЕТ" not in s[1] for s in sent), sent
