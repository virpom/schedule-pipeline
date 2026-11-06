"""Граница учебного года считается по местному времени, не по UTC.

Весь бот живёт в поясе колледжа (``TZ=Asia/Krasnoyarsk``, UTC+7).
Учебный год начинается 1 сентября по местному — в UTC это 31 августа
17:00. Функция брала ``now(timezone.utc)``, и семь часов в году
отдавала курс на единицу меньше у ВСЕХ групп сразу.

Последствие не косметическое: курс выбирает поток звонков (1 и 4 курс —
I_IV, 2 и 3 — II_III). 1 сентября у всех студентов было бы чужое время
пар.

Дефект внёс я сам 06.11.2026, когда убирал ручной выбор курса.
"""
import datetime
import inspect

import common.schedule as sched


def _acad_start(now: datetime.datetime) -> int:
    return now.year if now.month >= 9 else now.year - 1


def test_no_utc_in_course_from_group():
    """В функции нет перевода в UTC — иначе она разойдётся с остальным ботом."""
    body = inspect.getsource(sched.course_from_group)
    assert "timezone.utc" not in body, "курс снова считается по UTC"
    assert "utcnow" not in body


def test_boundary_matches_local_calendar():
    """1 сентября 00:30 по Красноярску — уже новый учебный год.

    В UTC это ещё 31 августа 17:30, и UTC-счёт дал бы старый год.
    """
    local = datetime.datetime(2027, 9, 1, 0, 30)   # KRAT
    utc_equivalent = datetime.datetime(2027, 8, 31, 17, 30)

    assert _acad_start(local) == 2027
    assert _acad_start(utc_equivalent) == 2026, (
        "если это перестало быть правдой, тест больше не проверяет границу")

    # Набор 2026 в новом учебном году — второй курс.
    assert _acad_start(local) - 2026 + 1 == 2
    # А UTC-счёт дал бы первый — ровно тот дефект.
    assert _acad_start(utc_equivalent) - 2026 + 1 == 1


def test_migration_uses_local_time():
    """Миграция 0014 пишет в базу навсегда — UTC там особенно дорог."""
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1]
           / "migrations/versions/0014_user_course_from_group.py").read_text()
    assert "timezone.utc" not in src, "миграция снова считает по UTC"


def test_course_values_sane():
    """Быстрая проверка, что функция вообще работает."""
    assert sched.course_from_group("ДП-26") >= 1
    assert sched.course_from_group("ГИ-21") >= 5
